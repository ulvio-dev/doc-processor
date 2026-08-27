# Tests

```bash
uv sync --group dev
uv run pytest              # ~25s, no network beyond a cached HF tokenizer
uv run pytest -q tests/test_api.py::test_queue_cap_rejects_the_eleventh_with_busy
```

No running server and no Redis is needed. The API tests drive the ASGI app
directly through `httpx.ASGITransport`, so a single test can hold fourteen SSE
streams open at once without fourteen sockets.

## Layout

| File | Covers | Runs docling? |
|---|---|---|
| [test_process_doc.py](test_process_doc.py) | conversion library: format detection, output selection, chunking params, progress callback | **yes** |
| [test_api.py](test_api.py) | HTTP contract: rejections, SSE framing, queueing, heartbeats, registry | no — stubbed |
| [conftest.py](conftest.py) | fixtures: sample `.docx`, reset app state, stubbed conversion | — |
| [util.py](util.py) | SSE parsing helpers | — |

## Two things worth knowing before editing these

**`.docx`, not `.pdf`.** The conversion tests use a `.docx` built at test time by
`python-docx` (so no binary fixture lives in the repo). `.docx` goes through
docling's `SimplePipeline`, which needs no ML models. A `.pdf` test would pull
~500 MB of layout models on a cold cache and make the suite unusable in CI. The
trade-off is real and deliberate: **PDF conversion itself is not covered here**,
only the plumbing around it.

**API tests stub docling.** `stub_conversion` swaps in a controllable `sleep`.
Queue behaviour needs jobs slow enough to overlap and fast enough for a test
suite, and 20 real conversions per run would take minutes. What is being tested
there is the queue and the stream, not the converter.

## The regression these exist for

`test_queue_cap_rejects_the_eleventh_with_busy` and
`test_queue_never_exceeds_the_cap` guard a bug that was live during development
and is easy to reintroduce.

The obvious way to write the endpoint — and the way the sibling
`roof-measurement` service does it, where there is no cap so it does not
matter — is to enqueue inside the SSE generator:

```python
async def event_stream():
    asyncio.create_task(_enqueue(job, send_event))   # ← too late
```

A `StreamingResponse` generator does not run until the client starts reading the
body. So every concurrent request passes the capacity check while the queue still
looks empty, and the cap silently does nothing: 14 concurrent uploads were all
accepted, and the observed queue depth hit 14 against a cap of 10.

The slot must therefore be reserved **synchronously in the request handler**,
with the authoritative depth check immediately before the append and no `await`
between them — `await request.form()` is exactly the kind of interleaving point
that breaks it.

## Not covered

- Real PDF conversion, and therefore OCR and table structure (see above)
- Legacy `.doc` end to end — needs LibreOffice on PATH; only the
  missing-LibreOffice error path is tested
- The frontend — no JS test setup, it is deliberately build-free
