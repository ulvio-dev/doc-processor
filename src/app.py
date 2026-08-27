"""
Doc processor: HTTP + SSE.

One endpoint does the work — POST /process takes a multipart upload and streams
the conversion back as Server-Sent Events, ending with the markdown and chunks
in the final event. There is no Redis, no database, and nothing on disk: the
payload lives in memory for exactly as long as the job does, and the result is
returned by value, never by URL.

Queueing is an in-process deque with concurrency 1, since docling saturates the
CPU it is given and a second concurrent conversion only makes both slower. The
queue holds at most MAX_QUEUE_ENTRIES entries; past that the service answers
429 Busy rather than accepting work it cannot start.

Shape (SSE events, the deque worker, the job registry) follows
ulvio-dev/roof-measurement so the two services read the same way.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
import traceback
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

from src import process_doc
from src.process_doc import (
    ACCEPTED_FORMATS,
    DEFAULTS,
    MAX_QUEUE_ENTRIES,
    MAX_UPLOAD_BYTES,
    OUTPUT_CHOICES,
    ProcessParams,
    UnsupportedFormat,
    detect_format,
    libreoffice_available,
    process_document,
)

# Starlette spools any upload over 1MB to a temporary *file*. This service
# promises the payload stays in memory, so raise the threshold above our own
# cap — the cap, not the spool, is what bounds memory here.
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + 1

HEARTBEAT_SECONDS = 15
MAX_JOB_HISTORY = 50

app = FastAPI(
    title="Doc Processor",
    version="2.0.0",
    description="Convert PDF/DOCX/DOC to markdown + chunks. POST /process, response is SSE.",
)


# ---------------------------------------------------------------------------
# In-process job queue (concurrency = 1)
# ---------------------------------------------------------------------------

_queue: deque = deque()
_processing = False

SendEvent = Callable[[dict], Coroutine[Any, Any, None]]

# Job registry, so /api/queue and the UI can *look at* the queue — the deque
# itself holds opaque (job, send_event) tuples. Bounded, in-memory, resets with
# the process. It deliberately never holds the payload bytes.
_jobs: "OrderedDict[str, dict]" = OrderedDict()
_job_ids = itertools.count(1)


def _register_job(job: dict) -> dict:
    record = {
        "id": f"job-{next(_job_ids):04d}",
        "status": "queued",
        "filename": job["filename"],
        "size_bytes": len(job["data"]),
        "params": job["params_summary"],
        "stage": None,
        "progress": 0,
        "position": None,
        "error": None,
        "summary": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    _jobs[record["id"]] = record
    while len(_jobs) > MAX_JOB_HISTORY:
        _jobs.popitem(last=False)
    return record


def _update_job(record: dict, event: dict) -> None:
    """Fold an outgoing SSE event into the registry record."""
    status = event.get("status")
    if status:
        record["status"] = status

    if status == "queued":
        record["position"] = event.get("position")
    elif status == "processing":
        if record["started_at"] is None:
            record["started_at"] = time.time()
        record["position"] = None
        record["stage"] = event.get("stage", record["stage"])
        record["progress"] = event.get("progress", record["progress"])
    elif status == "complete":
        record["finished_at"] = time.time()
        record["progress"] = 100
        record["stage"] = "done"
        record["position"] = None
        # The result itself is streamed to the client and dropped. Only a
        # summary is kept — retaining markdown for 50 jobs would make the
        # registry the memory hog the 20MB cap exists to prevent.
        result = event.get("result") or {}
        meta = result.get("meta") or {}
        record["summary"] = {
            "pages": meta.get("pages"),
            "chunk_count": meta.get("chunk_count"),
            "markdown_chars": len(result.get("markdown") or "") or None,
        }
    elif status == "error":
        record["finished_at"] = time.time()
        record["position"] = None
        record["error"] = event.get("message")


def _queue_depth() -> int:
    """Entries occupying the queue: waiting plus the one being processed."""
    return len(_queue) + (1 if _processing else 0)


def _enqueue(job: dict, send_event: SendEvent) -> tuple[dict, SendEvent]:
    """Reserve a queue slot and return (record, tracked sender).

    Deliberately synchronous. The queue cap is only meaningful if the slot is
    taken in the request handler, before the response is returned — doing it
    inside the SSE generator (which does not run until the client starts
    reading the body) lets any number of requests pass the cap check while the
    queue still looks empty.
    """
    record = _register_job(job)
    job["record"] = record

    async def tracked(event: dict) -> None:
        _update_job(record, event)
        await send_event(event)

    _queue.append((job, tracked))
    return record, tracked


async def _broadcast_positions() -> None:
    """Tell everyone still waiting where they now are."""
    for i, (_, notify) in enumerate(_queue):
        await notify({"status": "queued", "position": i + 1})


async def _process_next() -> None:
    global _processing
    if _processing or not _queue:
        return
    _processing = True
    job, send_event = _queue.popleft()
    await _broadcast_positions()
    try:
        if job.get("cancelled"):
            # Client hung up while it was waiting. Nothing to send it.
            return
        await _run_job(job, send_event)
    except Exception as e:
        traceback.print_exc()
        await send_event({"status": "error", "message": f"{type(e).__name__}: {e}"})
    finally:
        # Drop the payload the moment the job is done, either way.
        job["data"] = b""
        _processing = False
        await _process_next()


async def _run_job(job: dict, send_event: SendEvent) -> None:
    loop = asyncio.get_running_loop()

    await send_event({"status": "processing", "stage": "starting", "progress": 0})

    def progress(stage: str, pct: int) -> None:
        # Called from the worker thread — hop back onto the loop to send.
        if job.get("cancelled"):
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                send_event({"status": "processing", "stage": stage, "progress": pct})
            )
        )

    # docling is blocking and CPU-bound. Running it in a thread is what keeps
    # the heartbeat flowing during a multi-minute conversion.
    result = await asyncio.to_thread(
        process_document, job["data"], job["filename"], job["params"], progress
    )

    await send_event({"status": "complete", "result": result})


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_params(form) -> ProcessParams:
    output = (form.get("output") or DEFAULTS["output"]).strip().lower()
    if output not in OUTPUT_CHOICES:
        raise HTTPException(
            400, f"output must be one of {', '.join(OUTPUT_CHOICES)} (got {output!r})"
        )

    raw_tokens = form.get("max_tokens")
    max_tokens = None
    if raw_tokens not in (None, ""):
        try:
            max_tokens = int(raw_tokens)
        except ValueError:
            raise HTTPException(400, f"max_tokens must be an integer (got {raw_tokens!r})")
        if max_tokens < 1:
            raise HTTPException(400, "max_tokens must be positive")

    raw_lang = (form.get("ocr_lang") or "").strip()
    ocr_lang = [p.strip() for p in raw_lang.replace(" ", ",").split(",") if p.strip()]

    return ProcessParams(
        output=output,
        do_ocr=_as_bool(form.get("do_ocr"), DEFAULTS["do_ocr"]),
        ocr_lang=ocr_lang,
        max_tokens=max_tokens,
        tokenizer=(form.get("tokenizer") or DEFAULTS["tokenizer"]).strip(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _busy_response() -> JSONResponse:
    """The queue is full — reject rather than accept work we cannot start."""
    return JSONResponse(
        {
            "error": "Busy",
            "detail": f"queue is full ({MAX_QUEUE_ENTRIES} entries)",
            "queued": len(_queue),
            "processing": _processing,
        },
        status_code=429,
    )


@app.post("/process")
async def process(request: Request):
    """Convert one document. Multipart in, SSE out.

    Everything that can be rejected is rejected *before* the stream opens, so a
    client either gets a plain HTTP error or gets a stream that will finish.
    """
    # Cheap pre-check: refuse an oversized body before reading any of it.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES * 1.05:
        raise HTTPException(
            413,
            f"payload too large: {int(declared)} bytes, limit is {MAX_UPLOAD_BYTES} "
            f"({MAX_UPLOAD_BYTES // (1024 * 1024)}MB) per document",
        )

    if _queue_depth() >= MAX_QUEUE_ENTRIES:
        return _busy_response()

    try:
        form = await request.form(max_part_size=MAX_UPLOAD_BYTES + 1)
    except Exception:
        raise HTTPException(
            413,
            f"payload too large: limit is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB per document",
        )

    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, "a `file` part is required (multipart/form-data)")

    filename = upload.filename or ""
    try:
        detect_format(filename)
    except UnsupportedFormat as e:
        raise HTTPException(415, str(e))

    data = await upload.read()
    if len(data) == 0:
        raise HTTPException(400, "uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"payload too large: {len(data)} bytes, limit is {MAX_UPLOAD_BYTES} "
            f"({MAX_UPLOAD_BYTES // (1024 * 1024)}MB) per document",
        )

    params = _parse_params(form)

    job = {
        "data": data,
        "filename": filename,
        "params": params,
        "params_summary": {
            "output": params.output,
            "do_ocr": params.do_ocr,
            "ocr_lang": params.ocr_lang,
            "max_tokens": params.max_tokens or DEFAULTS["max_tokens"],
            "tokenizer": params.tokenizer,
        },
        "cancelled": False,
    }

    event_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def send_event(data: dict) -> None:
        await event_queue.put(data)

    # Authoritative capacity check. The cheap one above ran before `await
    # request.form()`, so re-check here where nothing can interleave between the
    # check and the append.
    if _queue_depth() >= MAX_QUEUE_ENTRIES:
        return _busy_response()

    record, tracked = _enqueue(job, send_event)

    # First event goes in synchronously, so the client sees its position even if
    # it starts reading late.
    initial = {"status": "queued", "position": len(_queue), "job_id": record["id"]}
    _update_job(record, initial)
    event_queue.put_nowait(initial)

    asyncio.create_task(_process_next())

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        event_queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    # Comment frame: keeps proxies and the browser from giving
                    # up on a conversion that legitimately takes minutes.
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("complete", "error"):
                    break
        finally:
            # Client disconnected (or we finished). Either way stop holding the
            # payload; if it never ran, _process_next will skip it.
            job["cancelled"] = True
            job["data"] = b""

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    """Liveness plus the environment facts that explain most failures."""
    return {
        "status": "healthy",
        "queued": len(_queue),
        "processing": _processing,
        # .doc conversion goes through LibreOffice. If this is false in a
        # deployment, .doc uploads fail and this is why.
        "libreoffice": libreoffice_available(),
        # None when the chunking tokenizer loaded. A string means the model cache
        # in this image is broken and chunking will fail — the single most likely
        # deployment problem, so it is reported rather than left to a stack trace.
        "tokenizer_error": process_doc.TOKENIZER_ERROR,
    }


@app.get("/api/queue")
async def api_queue():
    """Queue state plus recent history, newest job first."""
    return {
        "processing": _processing,
        "queued": len(_queue),
        "depth": _queue_depth(),
        "max_entries": MAX_QUEUE_ENTRIES,
        "jobs": list(reversed(list(_jobs.values()))),
    }


@app.get("/api/contract")
async def api_contract():
    """The contract, served by the thing that implements it.

    The frontend renders this instead of hardcoding a copy, so the documented
    limits and defaults are always the ones actually in force.
    """
    return {
        "endpoint": "POST /process",
        "encoding": "multipart/form-data",
        "response": "text/event-stream",
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_queue_entries": MAX_QUEUE_ENTRIES,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "accepted_extensions": sorted(ACCEPTED_FORMATS),
        "libreoffice": libreoffice_available(),
        "tokenizer_error": process_doc.TOKENIZER_ERROR,
        "defaults": DEFAULTS,
        "output_choices": list(OUTPUT_CHOICES),
    }


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"

if _STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

    @app.get("/")
    async def root():
        return RedirectResponse("/ui/")
