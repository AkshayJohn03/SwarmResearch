"""AsyncRuntime behaviour: ordering, fan-out limits, retry, timeout,
cancellation propagation, conditional routing, event ordering, spans."""

from __future__ import annotations

import asyncio

from swarm.orchestra.checkpoint import CheckpointStore
from swarm.orchestra.graph import Graph, Node, RetryPolicy
from swarm.orchestra.human import HumanInputQueue, HumanInterrupt, require_input
from swarm.orchestra.runtime import (
    AsyncRuntime,
    EventBus,
    GraphCompleted,
    NodeFailed,
    NodeFinished,
    NodeSkipped,
    NodeStarted,
)


def node(node_id: str, fn, **kwargs) -> Node:
    return Node(id=node_id, fn=fn, **kwargs)


def run_graph(graph: Graph, **kwargs):
    return asyncio.run(AsyncRuntime(graph, **kwargs).run())


# -- dependency ordering -------------------------------------------------


def test_execution_respects_dependency_order():
    finished: list[str] = []
    counters: dict[str, int] = {}

    def make(nid: str, **kw):
        async def fn(inputs, ctx):
            counters[nid] = counters.get(nid, 0) + 1
            await asyncio.sleep(0.01)
            finished.append(nid)
            return {f"out_{nid}": 1}

        return node(nid, fn, outputs=(f"out_{nid}",), **kw)

    g = Graph("order")
    for nid in ["a", "b", "c", "d"]:
        g.add_node(make(nid))
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("b", "d")
    g.add_edge("c", "d")
    result = run_graph(g)
    assert result.status == "completed"
    assert counters == {"a": 1, "b": 1, "c": 1, "d": 1}
    assert finished.index("a") < finished.index("b") < finished.index("d")
    assert finished.index("a") < finished.index("c") < finished.index("d")
    assert result.outputs["out_d"] == 1


# -- fan-out with semaphore ------------------------------------------------


def test_fanout_respects_max_concurrency():
    active = {"now": 0, "peak": 0}

    async def fan_fn(inputs, ctx):
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        await asyncio.sleep(0.03)
        active["now"] -= 1
        return {"x": 1}

    async def root_fn(inputs, ctx):
        return {"root_out": 1}

    g = Graph("fanout")
    g.add_node(node("root", root_fn, outputs=("root_out",)))
    for i in range(6):
        g.add_node(node(f"leaf{i}", fan_fn, inputs=("root_out",)))
        g.add_edge("root", f"leaf{i}")
    result = asyncio.run(AsyncRuntime(g, max_concurrency=2).run())
    assert result.status == "completed"
    assert active["peak"] <= 2, "semaphore was not respected"


# -- retry with backoff -------------------------------------------------------


def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    async def flaky(inputs, ctx):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return {"value": 42}

    g = Graph("retry")
    g.add_node(
        node(
            "flaky",
            flaky,
            outputs=("value",),
            retry=RetryPolicy(max_attempts=3, base_delay_ms=1, jitter_ms=0),
        )
    )
    events: list = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = asyncio.run(AsyncRuntime(g, event_bus=bus).run())
    assert result.status == "completed"
    assert result.outputs["value"] == 42
    started = [e.attempt for e in events if isinstance(e, NodeStarted)]
    assert started == [1, 2, 3]
    failures = [e for e in events if isinstance(e, NodeFailed)]
    assert len(failures) == 2 and all(f.recoverable for f in failures)


# -- timeout ---------------------------------------------------------------


def test_timeout_fails_node_and_skips_downstream():
    async def slow(inputs, ctx):
        await asyncio.sleep(1.0)
        return {"x": 1}

    g = Graph("timeout")
    g.add_node(node("slow", slow, outputs=("x",), timeout_ms=40, retry=RetryPolicy(max_attempts=1)))
    g.add_node(node("child", slow, inputs=("x",)))
    g.add_edge("slow", "child")
    events: list = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = asyncio.run(AsyncRuntime(g, event_bus=bus).run())
    assert result.status == "failed"
    assert [e.node_id for e in events if isinstance(e, NodeSkipped)] == ["child"]
    started_ids = [e.node_id for e in events if isinstance(e, NodeStarted)]
    assert "child" not in started_ids


# -- cancellation propagation ------------------------------------------------


def test_failure_cancels_transitive_downstream():
    async def boom(inputs, ctx):
        raise RuntimeError("unrecoverable")

    async def normal(inputs, ctx):
        return {"x": 1}

    g = Graph("cancel")
    g.add_node(node("boom", boom, outputs=("boom_out",), retry=RetryPolicy(max_attempts=1)))
    g.add_node(node("mid", normal, inputs=("boom_out",), outputs=("mid_out",)))
    g.add_node(node("leaf", normal, inputs=("mid_out",)))
    g.add_edge("boom", "mid")
    g.add_edge("mid", "leaf")
    events: list = []
    bus = EventBus()
    bus.subscribe(events.append)
    result = asyncio.run(AsyncRuntime(g, event_bus=bus).run())
    assert result.status == "failed"
    skipped = {e.node_id for e in events if isinstance(e, NodeSkipped)}
    assert skipped == {"mid", "leaf"}
    assert "RuntimeError: unrecoverable" in result.error


# -- conditional edges ----------------------------------------------------------


def test_router_selects_branch_and_skips_the_other():
    async def root_fn(inputs, ctx):
        return {"choice": "left"}

    async def passthrough(inputs, ctx):
        return {"x": 1}

    g = Graph("router")
    g.add_node(node("root", root_fn, outputs=("choice",)))
    g.add_node(node("left", passthrough, inputs=("choice",)))
    g.add_node(node("right", passthrough, inputs=("choice",)))
    g.add_edge("root", "left")
    g.add_edge("root", "right")
    g.node("root").router = lambda result: ["left"]
    result = run_graph(g)
    assert result.status == "completed"
    assert result.node_status["left"] == "completed"
    assert result.node_status["right"] == "skipped"


# -- event ordering + spans -------------------------------------------------------


def test_event_sequences_are_ordered_and_spans_are_wellformed():
    async def produce_v(inputs, ctx):
        return {"v": 1}

    async def produce_w(inputs, ctx):
        return {"w": 2}

    g = Graph("events")
    g.add_node(node("a", produce_v, outputs=("v",), stage="stage_a"))
    g.add_node(node("b", produce_w, inputs=("v",), outputs=("w",)))
    g.add_edge("a", "b")
    events: list = []
    spans: list[dict] = []
    bus = EventBus()
    bus.subscribe(events.append)
    asyncio.run(AsyncRuntime(g, event_bus=bus, span_sink=spans.append).run())
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)
    assert isinstance(events[-1], GraphCompleted)
    assert events[-1].status == "completed"

    assert spans, "span_sink never fired"
    for span in spans:
        assert set(span) == {"span_id", "parent_id", "name", "stage", "duration_ms", "status", "attrs"}
        assert span["parent_id"].startswith("run-")
    assert any(span["stage"] == "stage_a" for span in spans)
    assert [s for s in spans if s["status"] != "ok"] == []

    started = {e.node_id: e.sequence for e in events if isinstance(e, NodeStarted)}
    finished = {e.node_id: e.sequence for e in events if isinstance(e, NodeFinished)}
    assert finished["a"] < started["b"]


# -- human-in-the-loop --------------------------------------------------------------


def test_human_pause_and_resume():
    calls = {"ask": 0, "a": 0, "b": 0}

    async def a_fn(inputs, ctx):
        calls["a"] += 1
        return {"x": 1}

    async def ask_fn(inputs, ctx):
        calls["ask"] += 1
        answer = require_input(ctx.human, "Approve deployment?")
        return {"decision": answer}

    async def b_fn(inputs, ctx):
        calls["b"] += 1
        return {"echo": inputs["decision"]}

    g = Graph("human")
    g.add_node(node("a", a_fn, outputs=("x",)))
    g.add_node(node("ask", ask_fn, inputs=("x",), outputs=("decision",)))
    g.add_node(node("b", b_fn, inputs=("decision",)))
    g.add_edge("a", "ask")
    g.add_edge("ask", "b")

    store = CheckpointStore(":memory:")
    first = asyncio.run(
        AsyncRuntime(g, checkpoint=store, human_source=HumanInputQueue([]), run_id="h1").run()
    )
    assert first.status == "paused"
    assert calls["ask"] == 1 and calls["a"] == 1
    assert store.load_pause("h1")[0] == "ask"

    second = asyncio.run(
        AsyncRuntime(
            g,
            checkpoint=store,
            human_source=HumanInputQueue(["approved"]),
            run_id="h1",
        ).run(resume=True)
    )
    assert second.status == "completed"
    assert second.outputs["decision"] == "approved"
    # the paused node re-executed exactly once; finished nodes never did
    assert calls == {"ask": 2, "a": 1, "b": 1}


def test_human_interrupt_is_importable_surface():
    assert issubclass(HumanInterrupt, Exception)
