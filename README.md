# Doc Processor

Internal HTTP service that converts documents to markdown and chunked text with
[docling](https://github.com/docling-project/docling). Upload a document, get the
result back **on the same connection** — progress arrives as Server-Sent Events,
and the final event carries the markdown and the chunks.

Nothing is written to disk, nothing is returned by reference, and there is no
Redis, no database and no job id to poll.

> **Breaking change from 1.x.** This used to be a BullMQ/Redis worker that read
> file paths and wrote two files to disk. That interface is gone, along with all
> `REDIS_*` configuration. See [Migrating from 1.x](#migrating-from-1x).

There is a small web UI at `/` for trying conversions and checking service
state — **it is the first place to look when something is not right.**

## Quick start

```bash
docker run -p 8000:8000 ghcr.io/ulvio-dev/doc-processor:latest
open http://localhost:8000/
```

Locally, without Docker:

```bash
uv sync
uv run uvicorn main:app --port 8000
```

No authentication and no configuration: this is an internal service, and the
limits below are compiled in rather than tunable via environment variables.

## The contract

### `POST /process`

`multipart/form-data` in, `text/event-stream` out.

| Field | Type | Default | Notes |
|---|---|---|---|
| `file` | file | — | **required**, max 20 MB |
| `output` | `markdown` \| `chunks` \| `both` | `both` | skip work you do not need |
| `max_tokens` | int | `256` | chunk size; ignored when `output=markdown` |
| `tokenizer` | string | `sentence-transformers/all-MiniLM-L6-v2` | must be present in the image's model cache |
| `do_ocr` | bool | `true` | see [Performance](#performance) |
| `ocr_lang` | comma-separated | *(docling decides)* | e.g. `nl,fr`; only used when `do_ocr` |

Defaults are read off docling at startup rather than hardcoded, so
`GET /api/contract` always reports the ones actually in force. If a docling
upgrade changes one, that endpoint and the UI change with it — this table is the
copy that can go stale.

```bash
curl -N -X POST http://localhost:8000/process \
  -F "file=@report.pdf" \
  -F "output=both" \
  -F "max_tokens=256"
```

`-N` matters: without it curl buffers and you see nothing until the conversion
finishes.

### Events

```
data: {"status":"queued","position":2,"job_id":"job-0007"}
data: {"status":"processing","stage":"converting","progress":5}
data: {"status":"processing","stage":"chunking","progress":80}
data: {"status":"complete","result":{"markdown":"# ...","chunks":["..."],"meta":{...}}}
```

| Event | Carries |
|---|---|
| `queued` | `position`, `job_id`. Re-sent to everyone waiting as the queue drains. |
| `processing` | `stage` (`converting` / `exporting` / `chunking`), `progress` 0–100. |
| `complete` | `result.markdown`, `result.chunks[]`, `result.meta`. Terminal. |
| `error` | `message`. Terminal. |
| `: heartbeat` | Comment frame every 15s while otherwise silent. |

The heartbeat exists because a large PDF can take minutes; without it proxies
and browsers drop the connection. Clients must tolerate comment frames — they
are not JSON.

### Rejections

All of these happen **before** the stream opens, so a client either gets a plain
HTTP error or gets a stream that will finish.

| Status | When |
|---|---|
| `429` `{"error":"Busy"}` | queue already holds 10 entries (waiting + running) |
| `413` | document over 20 MB |
| `415` | anything other than `.pdf`, `.docx`, `.doc` |
| `400` | missing or empty `file` part, or an invalid parameter |

### Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | web UI |
| `GET /health` | liveness, queue depth, LibreOffice presence, tokenizer state |
| `GET /api/queue` | queue state and recent job history |
| `GET /api/contract` | the limits and defaults actually in force, as JSON |
| `GET /docs` | OpenAPI |

## Accepted formats

`.pdf`, `.docx` and `.doc`.

Legacy `.doc` works, but docling handles it by shelling out to LibreOffice to
produce a `.docx` first — which is why the image carries
`libreoffice-writer-nogui` and roughly 400 MB of its 2.3 GB. If `.doc` is not
worth that, drop `.doc` from `ACCEPTED_FORMATS` in
[src/process_doc.py](src/process_doc.py) and the apt line from the
[Dockerfile](Dockerfile) together.

`/health` reports `libreoffice: false` when it is missing, and the UI shows a
banner, so a `.doc` upload failing is diagnosable rather than mysterious.

docling itself supports far more (xlsx, pptx, html, images, audio). The narrow
list is deliberate: accepting a format means owning its failure modes.

## Queueing

One in-process `deque`, concurrency 1, capacity 10 including the job being
processed. Docling saturates whatever CPU it is given, so a second concurrent
conversion makes both slower rather than either faster.

The queue is in memory and dies with the process — that is the trade for having
no Redis. A restart drops queued work, and clients get a broken stream rather
than a resumable job. If durable jobs are ever needed, that is a different
service, not a flag on this one.

**Run one replica per pod and one uvicorn worker.** Each worker has its own
queue, so N workers means N independent queues and N concurrent conversions
fighting for the same cores — which is exactly what the cap exists to prevent.
Scale by adding pods behind a load balancer, accepting that the cap is then
per-pod.

## Performance

Conversion is CPU-bound and can take minutes on a large scanned PDF. The single
biggest lever available today is `do_ocr=false`, which is much faster on PDFs
that already have a text layer — and produces nothing useful on scans.

Broader performance work, including which docling version to pin, is tracked in
[#4](https://github.com/ulvio-dev/doc-processor/issues/4) and deliberately not
done here. Two findings from the build worth knowing:

- On Linux CPU, docling's default `auto` OCR resolves to **RapidOCR**, not
  EasyOCR.
- Table structure runs in `accurate` mode with 4 threads and is not currently
  exposed per request.

## Deployment notes

- **Models are baked into the image** and `HF_HUB_OFFLINE=1` is set, so a cold
  pod does not download hundreds of MB on its first request. A missing model
  fails loudly at startup instead.
- **Do not mount anything over `/opt/hf` or `/opt/torch`** — that is where the
  models live. They were moved off `/tmp` precisely because an emptyDir mount
  there would wipe them.
- **Memory** is bounded by the 20 MB cap times the queue depth, plus docling's
  own working set. The job registry keeps summaries only, never document
  content.
- `OMP_NUM_THREADS=4` is set to stop torch and OMP each sizing themselves to the
  node's core count and oversubscribing the pod's CPU quota. Match it to the
  actual CPU limit.

## Development

```bash
uv sync --group dev
uv run uvicorn main:app --port 8000 --reload
uv run pytest
```

See [tests/README.md](tests/README.md) for the test layout, and
[CLAUDE.md](CLAUDE.md) for how the pieces fit together.

The frontend has no build step — plain JSX compiled in the browser. Edit a file
under [src/static/](src/static/) and reload.

## Building the image

Builds are **manual on purpose**:

```bash
gh workflow run build.yml -f tag=2.0.0
```

`linux/amd64` only, pushed to `ghcr.io/ulvio-dev/doc-processor`. See
[.github/workflows/build.yml](.github/workflows/build.yml).

## Migrating from 1.x

| 1.x | 2.x |
|---|---|
| enqueue a BullMQ job on Redis | `POST /process` with the file |
| `inputFilePath` | the `file` part of the multipart body |
| `markdownOutputFilePath` | `result.markdown` in the `complete` event |
| `chunkedJsonOutputFilePath` | `result.chunks` in the `complete` event |
| poll the queue / watch the filesystem | read the SSE stream |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `QUEUE_NAME` | removed |

Callers no longer need a shared filesystem with this service, which was the main
reason for the change.
