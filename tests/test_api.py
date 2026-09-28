"""FastAPI surface: POST /research, SSE /research/stream, GET /runs/{id}.

Runs entirely in-process over httpx's ASGI transport -- no sockets, no
network, fully offline.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from swarm.app import create_app

QUERY = "What is the noise level of the XK-7 compressor module and how reliable is it?"


def parse_sse(lines: list[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for line in lines:
        if line.startswith("event: "):
            name = line[len("event: "):].strip()
        elif line.startswith("data: ") and name is not None:
            events.append((name, json.loads(line[len("data: "):])))
            name = None
    return events


def test_api_sse_end_to_end_ordered_events():
    async def scenario() -> tuple[str, list[tuple[str, dict]], dict]:
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post("/research", json={"query": QUERY, "offline": True})
            assert started.status_code == 200
            run_id = started.json()["run_id"]

            lines: list[str] = []
            done_seen = False
            async with client.stream(
                "GET", "/research/stream", params={"run_id": run_id}
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                async for line in response.aiter_lines():
                    lines.append(line)
                    if line == "event: done":
                        done_seen = True
                    elif done_seen and line.startswith("data: "):
                        break

            detail = await client.get(f"/runs/{run_id}")
            assert detail.status_code == 200
            return run_id, parse_sse(lines), detail.json()

    run_id, events, detail = asyncio.run(scenario())
    names = [name for name, _ in events]

    # stream shape: orchestrator events -> tokens -> report -> done
    assert "node_started" in names and "node_finished" in names
    assert names[-1] == "done"
    assert names.index("report") < names.index("done")
    token_indexes = [i for i, n in enumerate(names) if n == "token"]
    assert token_indexes, "report was not streamed as tokens"
    assert max(token_indexes) < names.index("report")

    # dependency ordering inside the orchestrator events
    position = {(n, payload.get("node_id")): i for i, (n, payload) in enumerate(events)}
    for i in range(4):
        assert position[("node_started", f"read-{i}")] > position[("node_finished", f"search-{i}")]
    assert position[("node_started", "analyze-0")] > position[("node_finished", "read-3")]
    assert position[("node_started", "critic-0")] > position[("node_finished", "analyze-0")]
    assert position[("node_started", "writer-0")] > min(
        position.get(("node_finished", "passthrough"), 10**9),
        position.get(("node_finished", "gapfill-analyze-0"), 10**9),
    )

    # final report arrived through the stream and via GET /runs/{id}
    report_payload = events[[n for n in names].index("report")][1]
    assert "XK-7" in report_payload["markdown"]
    assert detail["status"] == "completed"
    assert detail["metrics"]["hallucination_rate"] == 0.0
    assert run_id


def test_api_unknown_run_returns_404():
    async def scenario() -> tuple[int, int]:
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_run = await client.get("/runs/does-not-exist")
            stream_missing = await client.get(
                "/research/stream", params={"run_id": "does-not-exist"}
            )
            return missing_run.status_code, stream_missing.status_code

    assert asyncio.run(scenario()) == (404, 404)
