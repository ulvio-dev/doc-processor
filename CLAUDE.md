# CLAUDE.md

Guidance for working in this repository. See [README.md](README.md) for the HTTP
contract — this file is about the code.

## What this is

A single FastAPI app that wraps docling. One endpoint does the work; everything
else is introspection or the UI. There is no worker, no broker and no database.

```
main.py                     uvicorn entry point (`uvicorn main:app`)
src/app.py                  HTTP + SSE, the in-process queue, the job registry
src/process_doc.py          docling wrapper: bytes in, {markdown, chunks, meta} out
src/static/                 build-free React UI, mounted at /ui
tests/                      pytest (backend) + tests/frontend (jsdom)
Dockerfile                  amd64 only, models baked in
.github/workflows/build.yml  manual image build → GHCR
```

## Commands

```bash
uv sync --group dev
uv run uvicorn main:app --port 8000 --reload
uv run pytest
cd tests/frontend && npm install && npm test     # optional, needs npm
gh workflow run build.yml -f tag=2.0.1           # builds are manual on purpose
```

Never `pip install` here — dependencies live in `pyproject.toml` + `uv.lock`.

## Constraints that are load-bearing

Each of these looks like an arbitrary choice and is not. Changing one without
reading why will break something that tests may not catch.

**The queue slot is reserved synchronously in the request handler.** A
`StreamingResponse` generator does not run until the client starts reading the
body, so enqueueing inside `event_stream()` makes the capacity cap a no-op —
every concurrent request passes the check while the queue still looks empty
(measured: 14 accepted against a cap of 10). The authoritative depth check must
sit immediately before `_queue.append` with **no `await` between them**;
`await request.form()` is exactly the interleaving point that breaks it. Guarded
by `test_queue_cap_rejects_the_eleventh_with_busy`.

**Concurrency is 1, and there is one uvicorn worker.** Docling saturates its CPU
budget; overlapping conversions make both slower. Each worker would get its own
queue, so more workers means more independent queues and the cap stops meaning
anything. Scale with pods, not workers.

**`MultiPartParser.spool_max_size` is raised in `src/app.py`.** Starlette spools
uploads over 1 MB to a temp *file*, which contradicts the in-memory promise. The
20 MB cap is what bounds memory; the spool must not be.

**Docling runs in a thread** (`asyncio.to_thread`). It is blocking and CPU-bound,
and the event loop has to stay free to send heartbeats during a multi-minute
conversion. Progress callbacks come back from that thread via
`loop.call_soon_threadsafe`.

**Parameter defaults are read off docling at import**, into `DEFAULTS` in
`src/process_doc.py`, and served from `GET /api/contract`. The README table and
the UI are both downstream of that. Do not hardcode a default in the UI — it
will drift from what the service does on the next docling upgrade.

**A broken tokenizer must not be fatal.** `DEFAULTS` touches the HF cache, so a
bad model cache used to kill the process at import — taking down the UI that is
supposed to tell you what is wrong. It now degrades: `TOKENIZER_ERROR` is set,
reported on `/health`, and shown as a banner.

**The job registry never holds document content.** Summaries only. Retaining
markdown for 50 jobs would defeat the 20 MB cap.

## Docker gotchas

All three of these were found by building the image, not by reading it.

**torch must be declared directly in `pyproject.toml`.** `[tool.uv.sources]`
only redirects *direct* dependencies. torch arrives via docling, so without the
explicit `torch`/`torchvision` entries the CPU index is silently ignored and the
image gets the multi-GB CUDA build (`2.13.0+cu130`). Verify after any dependency
change:

```bash
docker run --rm doc-processor:test python -c "import torch; print(torch.__version__)"
# must print +cpu
```

**Chunks are emitted via `chunker.contextualize(chunk)`, never `chunk.text`.**
`chunk.text` is the body only; the headings live in `chunk.meta`, and dropping
them makes a list item under one section indistinguishable from the same item
under another. `HybridChunker` already counts tokens on the contextualized form,
so the `max_tokens` budget assumes the headings are there. Guarded by
`test_chunks_carry_their_heading_context`.

**`DEFAULT_MAX_TOKENS = 350` is ours, not docling's.** Every other entry in
`DEFAULTS` is read off docling at import so the UI and README cannot drift; this
one deliberately overrides it (docling derives 256 from the all-MiniLM-L6-v2
config). `_build_chunker` therefore always constructs the tokenizer explicitly —
the old shortcut to a bare `HybridChunker()` would silently reinstate 256.

**The `HybridChunker()` call in `_docling_defaults()` is a probe, not a read.**
Its return value is discarded, but it is what sets `TOKENIZER_ERROR` when the
model cache is broken, which `/health` and the UI report. Deleting it moves that
failure to the first request.

**`libgl1` and `libglib2.0-0` are mandatory.** On Linux CPU, docling's default
`auto` OCR resolves to RapidOCR, which imports `cv2`. Without `libGL.so.1` even
`docling-tools models download` fails at build time.

**Models are warmed at build time, not copied in.** The repo used to carry a
`.hybrid-chunk-model/` cache tree; docling 2.123's tokenizer also loads the
model's `config.json`, which that tree lacks, so the service died at import
under `HF_HUB_OFFLINE`. The Dockerfile instantiates `HybridChunker()` during the
build instead. Do not reintroduce a hand-maintained cache.

Model caches live in `/opt/hf` and `/opt/torch`, deliberately not `/tmp` — an
emptyDir mounted over `/tmp` would wipe them.

## Frontend

React 18 + Babel standalone + Tailwind, all from CDN, no build step, mirroring
`ulvio-dev/roof-measurement`. Components hang off `window`; every file must end
with `window.X = X` and be listed in `index.html` **in dependency order**.

Palette is neutral — black, white, gray. Red is reserved for genuine failure
states so that it means something.

The UI is meant to be the first place you look when something is wrong, so the
header surfaces the things that actually break deployments (unreachable service,
missing LibreOffice, broken tokenizer, full queue) and errors are shown in the
service's own words rather than paraphrased.

Since there is no bundler, nothing catches a typo'd component name — the failure
mode is a blank page. `tests/frontend` renders the whole UI in jsdom to catch
that; run it after touching `src/static/`.

## Scope

Docling version choice and processing-speed work belong to
[#4](https://github.com/ulvio-dev/doc-processor/issues/4), not here. The docling
constraint is intentionally unpinned in `pyproject.toml` with the resolved
version recorded in `uv.lock`.

## Conventions

- Comments explain *why*, especially where the obvious implementation is wrong —
  most of this file's content started as a comment in the code.
- Errors reach the caller in the service's own words. Do not soften them.
- Prefer adding a fact to `/api/contract` or `/health` over documenting it in two
  places.
