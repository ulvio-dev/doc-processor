# Tests

Two suites, run separately — the Python one is the one that matters day to day.

```bash
# Backend (43 tests, ~25s, no network beyond a cached HF tokenizer)
uv sync --group dev
uv run pytest
uv run pytest -q tests/test_api.py::test_queue_cap_rejects_the_eleventh_with_busy

# Frontend (18 checks, optional — needs npm)
cd tests/frontend && npm install && npm test
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
| [frontend/render.test.js](frontend/render.test.js) | renders the UI in jsdom: components resolve, the page says what it should | no — stubbed |

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

## The frontend test, and why it exists

The UI has **no build step**, so nothing catches a typo'd component name or a
missing `window.X =` export. The failure mode is a blank page in production.

`tests/frontend/render.test.js` loads React's UMD builds and every component
into jsdom as real `<script>` elements, exactly as `index.html` does, mounts
`<App />` with the endpoints stubbed from `fixtures/`, and asserts the rendered
text. It also checks that parameter defaults shown in the form come from
`/api/contract` rather than being hardcoded.

It is deliberately **not** wired into `pytest`: it needs `npm install`, and the
Python suite should stay runnable with nothing but `uv`.

One trap worth recording. Injecting the compiled code as `<script>` elements
with jsdom `runScripts` enabled is what makes the test meaningful. Using
`window.eval(code)` instead resolves bare identifiers in Node's scope rather
than the page's, so every cross-file component reference looks undefined and the
test fails for reasons the browser never would — `StatusBar is not defined`,
from a `StatusBar.js` that is perfectly fine.

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
- Frontend behaviour beyond first render: the SSE client, upload validation and
  the result tabs are not driven by the render test — it checks the page mounts
  and displays the right things, not that clicking Convert works
