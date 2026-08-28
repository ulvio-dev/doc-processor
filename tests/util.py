"""SSE parsing helpers for the API tests."""
from __future__ import annotations

import json


async def read_sse(response) -> list:
    """Drain an SSE response into a list of events.

    Heartbeats are comment frames (`: heartbeat`) with no data, so they arrive
    as the string "heartbeat" to keep assertions about them readable; JSON data
    frames arrive as dicts.
    """
    events: list = []
    async for line in response.aiter_lines():
        if line.startswith(": heartbeat"):
            events.append("heartbeat")
        elif line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def statuses(events: list) -> list[str]:
    return [e["status"] for e in events if isinstance(e, dict)]


def positions(events: list) -> list[int]:
    return [
        e["position"]
        for e in events
        if isinstance(e, dict) and e.get("status") == "queued"
    ]


def final(events: list) -> dict:
    data = [e for e in events if isinstance(e, dict)]
    assert data, "stream carried no data frames"
    return data[-1]
