"""FastAPI service and CLI entrypoint.

Endpoints:
    POST /research          start a research run (returns run_id immediately)
    GET  /research/stream   SSE: node events -> report tokens -> report -> done
    GET  /runs/{run_id}     status / report / metrics

CLI:
    swarm research "query" --offline --stream
    swarm serve --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from swarm.orchestra.runtime import GraphCompleted, RuntimeEvent
from swarm.pipeline import ResearchPipeline, ResearchRunResult
from swarm.settings import SwarmSettings

logger = logging.getLogger("swarm.app")

# Runtime dataclass names -> lower-case SSE event names.
_SSE_NAMES = {
    "NodeStarted": "node_started",
    "NodeFinished": "node_finished",
    "NodeFailed": "node_failed",
    "NodeSkipped": "node_skipped",
    "NodePaused": "node_paused",
    "GraphCompleted": "graph_completed",
}


class ResearchRequest(BaseModel):
    query: str
    offline: bool = True


@dataclass
class RunHandle:
    run_id: str
    query: str
    status: str = "running"
    log: EventLog = field(default_factory=lambda: EventLog())
    report: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    error: str | None = None


class EventLog:
    """Append-only event log with a live-tail async iterator."""

    def __init__(self) -> None:
        self._items: list[RuntimeEvent] = []
        self._cond = asyncio.Condition()

    def append(self, event: RuntimeEvent) -> None:
        self._items.append(event)

    def notify(self) -> None:
        async def _notify() -> None:
            async with self._cond:
                self._cond.notify_all()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify())
        except RuntimeError:  # no loop (e.g. replays after run completed)
            pass

    async def stream(self, timeout_s: float = 60.0):
        index = 0
        while True:
            if index >= len(self._items):
                try:
                    async with self._cond:
                        await asyncio.wait_for(
                            # bind index so the predicate sees the current cursor
                            self._cond.wait_for(lambda idx=index: len(self._items) > idx),
                            timeout=timeout_s,
                        )
                except TimeoutError:
                    return
            item = self._items[index]
            index += 1
            yield item
            if isinstance(item, GraphCompleted):
                return


def create_app(settings: SwarmSettings | None = None) -> FastAPI:
    settings = settings or SwarmSettings()
    app = FastAPI(title="SwarmResearch", version="0.1.0")
    runs: dict[str, RunHandle] = {}

    async def _execute(handle: RunHandle, pipeline: ResearchPipeline) -> None:
        try:
            result: ResearchRunResult = await pipeline.run(handle.query, run_id=handle.run_id)
            handle.report = result.report
            handle.metrics = result.metrics
            handle.status = result.status
            if result.status != "completed":
                handle.error = f"run ended with status '{result.status}'"
        except Exception as exc:  # noqa: BLE001 - API boundary; error surfaced to client
            handle.status = "failed"
            handle.error = f"{type(exc).__name__}: {exc}"
            logger.exception("research run failed")
        finally:
            handle.log.append(
                GraphCompleted(
                    run_id=handle.run_id,
                    status=handle.status,
                    duration_ms=0.0,
                    error=handle.error,
                )
            )
            handle.log.notify()

    @app.post("/research")
    async def start_research(request: ResearchRequest) -> dict:
        run_settings = settings.model_copy(update={"offline": request.offline})
        pipeline = ResearchPipeline(run_settings)
        import uuid

        handle = RunHandle(run_id=uuid.uuid4().hex[:12], query=request.query)
        runs[handle.run_id] = handle
        pipeline.event_bus.subscribe(lambda event: (handle.log.append(event), handle.log.notify()))
        asyncio.create_task(_execute(handle, pipeline))
        return {"run_id": handle.run_id, "status": "running", "stream": f"/research/stream?run_id={handle.run_id}"}

    @app.get("/research/stream")
    async def stream_research(run_id: str) -> StreamingResponse:
        handle = runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail="unknown run_id")

        async def sse():
            async for event in handle.log.stream():
                name = _SSE_NAMES.get(type(event).__name__, type(event).__name__)
                payload = {
                    "type": name,
                    "run_id": getattr(event, "run_id", run_id),
                    "node_id": getattr(event, "node_id", None),
                    "attempt": getattr(event, "attempt", None),
                    "status": getattr(event, "status", None),
                    "error": getattr(event, "error", None),
                }
                yield f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"
            if handle.error and not handle.report:
                yield f"event: error\ndata: {json.dumps({'error': handle.error})}\n\n"
            else:
                words = handle.report.split()
                for i in range(0, len(words), 40):
                    chunk = " ".join(words[i : i + 40])
                    yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
                yield f"event: report\ndata: {json.dumps({'run_id': run_id, 'markdown': handle.report})}\n\n"
            yield f"event: done\ndata: {json.dumps({'run_id': run_id})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        handle = runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail="unknown run_id")
        return {
            "run_id": handle.run_id,
            "query": handle.query,
            "status": handle.status,
            "metrics": handle.metrics,
            "error": handle.error,
            "report": handle.report or None,
        }

    return app


# -- CLI ----------------------------------------------------------------------


async def _cli_research(args: argparse.Namespace) -> int:
    settings = SwarmSettings(offline=not args.live)
    pipeline = ResearchPipeline(settings)
    if args.stream:
        pipeline.event_bus.subscribe(_print_event)
    result = await pipeline.run(args.query)
    print(result.report)
    return 0 if result.status == "completed" else 1


def _print_event(event: RuntimeEvent) -> None:
    name = type(event).__name__
    node = getattr(event, "node_id", "")
    status = getattr(event, "status", "") or getattr(event, "reason", "") or getattr(event, "error", "") or ""
    print(f"[{name}] {node} {status}".rstrip(), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarm", description="SwarmResearch multiagent deep-research assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    research = sub.add_parser("research", help="run a research query")
    research.add_argument("query")
    research.add_argument("--offline", action="store_true", default=True, help="bundled corpus + extractive mode (default)")
    research.add_argument("--live", action="store_true", help="use configured LLM/web endpoints if available")
    research.add_argument("--stream", action="store_true", help="print orchestrator events as they happen")

    serve = sub.add_parser("serve", help="start the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "research":
        return asyncio.run(_cli_research(args))
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(), host=args.host, port=args.port)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
