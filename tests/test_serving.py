"""Serving hardening: API-key auth, correlation ids, request-size limits.

Runs entirely in-process over httpx's ASGI transport -- no sockets, no
network, fully offline.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from swarm.app import create_app

QUERY = "What is the noise level of the XK-7 compressor module and how reliable is it?"


async def _wait_for_run(
    client: httpx.AsyncClient, run_id: str, timeout_s: float = 30.0, headers: dict | None = None
) -> dict:
    delay = 0.05
    elapsed = 0.0
    while True:
        detail = (await client.get(f"/runs/{run_id}", headers=headers)).json()
        if detail["status"] != "running" or elapsed >= timeout_s:
            return detail
        await asyncio.sleep(delay)
        elapsed += delay


def test_auth_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SWARM_API_KEYS", raising=False)
    app = create_app()

    async def scenario() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post("/research", json={"query": QUERY, "offline": True})
            detail = await _wait_for_run(client, started.json()["run_id"])
            return started.status_code, detail["status"] == "completed"

    started_status, completed = asyncio.run(scenario())
    assert started_status == 200
    assert completed


def test_auth_enforced_when_swarm_api_keys_set(monkeypatch):
    monkeypatch.setenv("SWARM_API_KEYS", "secret-a,secret-b")
    app = create_app()

    async def scenario() -> dict[str, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.post("/research", json={"query": QUERY})
            wrong = await client.post(
                "/research", json={"query": QUERY}, headers={"X-API-Key": "not-a-key"}
            )
            runs_no_key = await client.get("/runs/does-not-exist")
            started = await client.post(
                "/research", json={"query": QUERY, "offline": True}, headers={"X-API-Key": "secret-a"}
            )
            detail = await _wait_for_run(client, started.json()["run_id"], headers={"X-API-Key": "secret-a"})
            # /health and /metrics are exempt even though no handler exists yet:
            # they must answer 404 (missing route), never 401.
            health_exempt = await client.get("/health")
            metrics_exempt = await client.get("/metrics")
            return {
                "missing": missing.status_code,
                "wrong": wrong.status_code,
                "runs_no_key": runs_no_key.status_code,
                "started": started.status_code,
                "completed": detail["status"] == "completed",
                "health_exempt": health_exempt.status_code,
                "metrics_exempt": metrics_exempt.status_code,
            }

    result = asyncio.run(scenario())
    assert result["missing"] == result["wrong"] == result["runs_no_key"] == 401
    assert result["started"] == 200 and result["completed"]
    assert result["health_exempt"] == result["metrics_exempt"] == 404


def test_auth_generic_401_message(monkeypatch):
    monkeypatch.setenv("SWARM_API_KEYS", "secret-a")
    app = create_app()

    async def scenario() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/runs/x")).json()["detail"]

    assert asyncio.run(scenario()) == "Unauthorized: missing or invalid API key."


def test_correlation_id_echoed_and_returned(monkeypatch):
    monkeypatch.delenv("SWARM_API_KEYS", raising=False)
    app = create_app()

    async def scenario() -> tuple[str | None, str]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post(
                "/research",
                json={"query": QUERY, "offline": True},
                headers={"X-Correlation-ID": "cid-swarm-1"},
            )
            await _wait_for_run(client, started.json()["run_id"])
            return started.headers.get("x-correlation-id"), started.json()["correlation_id"]

    header, body_cid = asyncio.run(scenario())
    assert header == "cid-swarm-1"
    assert body_cid == "cid-swarm-1"


def test_correlation_id_generated_when_absent(monkeypatch):
    monkeypatch.delenv("SWARM_API_KEYS", raising=False)
    app = create_app()

    async def scenario() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post("/research", json={"query": QUERY, "offline": True})
            await _wait_for_run(client, started.json()["run_id"])
            return started.headers["x-correlation-id"]

    generated = asyncio.run(scenario())
    assert generated and generated != "cid-swarm-1"


def test_oversized_research_body_rejected_413(monkeypatch):
    monkeypatch.delenv("SWARM_API_KEYS", raising=False)
    app = create_app()

    async def scenario() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/research", json={"query": "x" * (8 * 1024 + 1)})
            return r.status_code

    assert asyncio.run(scenario()) == 413


@pytest.mark.parametrize("path", ["/runs/does-not-exist"])
def test_unknown_run_still_404(monkeypatch, path):
    monkeypatch.delenv("SWARM_API_KEYS", raising=False)
    app = create_app()

    async def scenario() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get(path)).status_code

    assert asyncio.run(scenario()) == 404
