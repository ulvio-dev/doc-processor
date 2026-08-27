"""The HTTP + SSE contract.

Conversion is stubbed here (see the `stub_conversion` fixture) so these tests
exercise queueing, rejection and streaming rather than docling. Real conversion
lives in test_process_doc.py.
"""
from __future__ import annotations

import asyncio

import pytest

from src.process_doc import MAX_QUEUE_ENTRIES, MAX_UPLOAD_BYTES
from tests.util import final, positions, read_sse, statuses

# ---------------------------------------------------------------------------
# Introspection endpoints
# ---------------------------------------------------------------------------

async def test_health_reports_queue_and_libreoffice(client):
    async with client as c:
        body = (await c.get("/health")).json()
    assert body["status"] == "healthy"
    assert body["queued"] == 0
    assert body["processing"] is False
    # .doc support hinges on this, so it must always be reported.
    assert isinstance(body["libreoffice"], bool)
    # None here means the chunking tokenizer loaded; a string is the reason it
    # did not. Either way the key must exist, since the UI keys off it.
    assert "tokenizer_error" in body


async def test_health_reports_a_broken_tokenizer_instead_of_hiding_it(client, app_module, monkeypatch):
    """A broken model cache must be visible, not fatal.

    The service deliberately starts with an unusable tokenizer so the frontend
    can say what is wrong; if it exited at import there would be nothing to ask.
    """
    monkeypatch.setattr("src.process_doc.TOKENIZER_ERROR", "OSError: no cached model")
    async with client as c:
        body = (await c.get("/health")).json()
    assert body["status"] == "healthy"
    assert body["tokenizer_error"] == "OSError: no cached model"


async def test_contract_endpoint_states_the_real_limits(client):
    async with client as c:
        body = (await c.get("/api/contract")).json()
    assert body["max_upload_bytes"] == MAX_UPLOAD_BYTES
    assert body["max_queue_entries"] == MAX_QUEUE_ENTRIES
    assert sorted(body["accepted_extensions"]) == [".doc", ".docx", ".pdf"]
    assert body["output_choices"] == ["markdown", "chunks", "both"]
    assert "max_tokens" in body["defaults"]


async def test_root_redirects_to_the_ui(client):
    async with client as c:
        r = await c.get("/", follow_redirects=False)
    assert r.status_code in (307, 302)
    assert r.headers["location"] == "/ui/"


# ---------------------------------------------------------------------------
# Rejections — all before the stream opens
# ---------------------------------------------------------------------------

async def test_unsupported_extension_is_415(client, upload):
    async with client as c:
        r = await c.post("/process", files=upload("notes.txt"))
    assert r.status_code == 415
    assert ".pdf" in r.json()["detail"]


async def test_oversized_payload_is_413(client, upload):
    oversized = b"%PDF-1.4\n" + b"0" * (MAX_UPLOAD_BYTES + 1024)
    async with client as c:
        r = await c.post("/process", files=upload("big.pdf", oversized))
    assert r.status_code == 413
    assert "20MB" in r.json()["detail"]


async def test_missing_file_part_is_400(client):
    async with client as c:
        r = await c.post("/process", data={"output": "both"})
    assert r.status_code == 400


async def test_empty_file_is_400(client, upload):
    async with client as c:
        r = await c.post("/process", files=upload("empty.pdf", b""))
    assert r.status_code == 400


async def test_invalid_output_is_400(client, upload, stub_conversion):
    stub_conversion()
    async with client as c:
        r = await c.post("/process", files=upload(), data={"output": "yaml"})
    assert r.status_code == 400


async def test_invalid_max_tokens_is_400(client, upload, stub_conversion):
    stub_conversion()
    async with client as c:
        r = await c.post("/process", files=upload(), data={"max_tokens": "lots"})
    assert r.status_code == 400


async def test_a_rejection_never_reserves_a_queue_slot(client, upload, app_module):
    async with client as c:
        await c.post("/process", files=upload("notes.txt"))
    assert len(app_module._queue) == 0
    assert app_module._jobs == {}


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

async def test_process_streams_queued_processing_complete(client, upload, stub_conversion):
    stub_conversion(seconds=0.05)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = await read_sse(r)

    seen = statuses(events)
    assert seen[0] == "queued"
    assert "processing" in seen
    assert seen[-1] == "complete"

    result = final(events)["result"]
    assert result["markdown"]
    assert result["chunks"]


async def test_result_is_returned_by_value_not_by_reference(client, upload, stub_conversion):
    """The whole point of the rewrite: no paths, no URLs, no job ids to fetch."""
    stub_conversion(seconds=0.05)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            events = await read_sse(r)

    result = final(events)["result"]
    assert set(result) == {"markdown", "chunks", "meta"}
    blob = str(result)
    assert "http://" not in blob and "https://" not in blob
    assert "/tmp" not in blob


async def test_parameters_reach_the_conversion(client, upload, app_module, monkeypatch):
    captured = {}

    def fake(data, filename, params=None, progress=None):
        captured["params"] = params
        return {"markdown": "x", "chunks": ["x"], "meta": {"chunk_count": 1}}

    monkeypatch.setattr(app_module, "process_document", fake)

    async with client as c:
        async with c.stream(
            "POST",
            "/process",
            files=upload(),
            data={"output": "chunks", "do_ocr": "false", "max_tokens": "77",
                  "ocr_lang": "nl,fr"},
        ) as r:
            await read_sse(r)

    params = captured["params"]
    assert params.output == "chunks"
    assert params.do_ocr is False
    assert params.max_tokens == 77
    assert params.ocr_lang == ["nl", "fr"]


async def test_conversion_failure_becomes_an_error_event(client, upload, stub_conversion):
    stub_conversion(fail=True)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            assert r.status_code == 200      # the stream opened; the job then failed
            events = await read_sse(r)

    assert statuses(events)[-1] == "error"
    assert "boom" in final(events)["message"]


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

async def _stream_one(c, upload, name, out):
    async with c.stream("POST", "/process", files=upload(name)) as r:
        if r.status_code != 200:
            out.append(("rejected", r.status_code, (await r.aread()).decode()))
            return
        out.append(("accepted", 200, await read_sse(r)))


async def test_queue_cap_rejects_the_eleventh_with_busy(client, upload, stub_conversion):
    """The cap is only real if the slot is reserved in the handler.

    Reserving inside the SSE generator instead lets every request pass the check
    while the queue still looks empty, because the generator does not run until
    the client starts reading the body.
    """
    stub_conversion(seconds=0.6)
    out: list = []
    async with client as c:
        await asyncio.gather(
            *[_stream_one(c, upload, f"d{i}.docx", out) for i in range(MAX_QUEUE_ENTRIES + 4)]
        )

    accepted = [o for o in out if o[0] == "accepted"]
    rejected = [o for o in out if o[0] == "rejected"]
    assert len(accepted) == MAX_QUEUE_ENTRIES
    assert len(rejected) == 4
    for _, status, body in rejected:
        assert status == 429
        assert '"Busy"' in body


async def test_queue_never_exceeds_the_cap(client, upload, stub_conversion, app_module):
    stub_conversion(seconds=0.5)
    depths: list[int] = []
    out: list = []

    async def watch(stop: asyncio.Event):
        while not stop.is_set():
            depths.append(app_module._queue_depth())
            await asyncio.sleep(0.01)

    stop = asyncio.Event()
    async with client as c:
        watcher = asyncio.create_task(watch(stop))
        await asyncio.gather(
            *[_stream_one(c, upload, f"d{i}.docx", out) for i in range(MAX_QUEUE_ENTRIES + 4)]
        )
        stop.set()
        await watcher

    assert max(depths) <= MAX_QUEUE_ENTRIES


async def test_waiting_clients_see_their_position_count_down(client, upload, stub_conversion):
    stub_conversion(seconds=0.3)
    out: list = []
    async with client as c:
        await asyncio.gather(*[_stream_one(c, upload, f"d{i}.docx", out) for i in range(3)])

    # The last client in has the longest countdown; whichever stream saw the most
    # queued events must have seen them strictly decreasing, ending at 1.
    countdowns = [positions(o[2]) for o in out if o[0] == "accepted"]
    longest = max(countdowns, key=len)
    assert len(longest) >= 2
    assert longest == sorted(longest, reverse=True)
    assert longest[-1] == 1


async def test_jobs_run_one_at_a_time(client, upload, app_module, monkeypatch):
    """Concurrency 1 — docling saturates its CPU budget, overlap only slows it."""
    concurrent = 0
    peak = 0

    def fake(data, filename, params=None, progress=None):
        nonlocal concurrent, peak
        import time
        concurrent += 1
        peak = max(peak, concurrent)
        time.sleep(0.15)
        concurrent -= 1
        return {"markdown": "x", "chunks": ["x"], "meta": {"chunk_count": 1}}

    monkeypatch.setattr(app_module, "process_document", fake)
    out: list = []
    async with client as c:
        await asyncio.gather(*[_stream_one(c, upload, f"d{i}.docx", out) for i in range(5)])

    assert peak == 1


async def test_heartbeats_keep_a_slow_stream_alive(client, upload, stub_conversion, app_module, monkeypatch):
    """A conversion emitting no progress must still produce comment frames."""
    monkeypatch.setattr(app_module, "HEARTBEAT_SECONDS", 0.1)
    stub_conversion(seconds=0.6, emit_progress=False)

    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            events = await read_sse(r)

    assert "heartbeat" in events
    assert statuses(events)[-1] == "complete"


async def test_queue_endpoint_records_a_finished_job(client, upload, stub_conversion):
    stub_conversion(seconds=0.05)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            await read_sse(r)
        body = (await c.get("/api/queue")).json()

    assert body["queued"] == 0
    assert body["processing"] is False
    assert body["max_entries"] == MAX_QUEUE_ENTRIES
    job = body["jobs"][0]
    assert job["status"] == "complete"
    assert job["filename"] == "report.docx"
    assert job["progress"] == 100
    assert job["summary"]["chunk_count"] == 1


async def test_registry_keeps_a_summary_not_the_document(client, upload, stub_conversion):
    """50 jobs' worth of retained markdown would defeat the 20MB cap."""
    stub_conversion(seconds=0.05)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            await read_sse(r)
        job = (await c.get("/api/queue")).json()["jobs"][0]

    assert "markdown" not in job and "chunks" not in job and "data" not in job
    assert set(job["summary"]) == {"pages", "chunk_count", "markdown_chars"}


async def test_payload_is_released_when_the_job_finishes(client, upload, stub_conversion, app_module):
    stub_conversion(seconds=0.05)
    async with client as c:
        async with c.stream("POST", "/process", files=upload()) as r:
            await read_sse(r)

    # Nothing in the registry or the queue still holds the bytes.
    assert len(app_module._queue) == 0
