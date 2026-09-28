"""Checkpoint semantics: crash mid-run, resume, no re-execution of done nodes."""

from __future__ import annotations

import asyncio

from swarm.orchestra.checkpoint import CheckpointStore
from swarm.orchestra.graph import Graph, Node, RetryPolicy
from swarm.orchestra.runtime import AsyncRuntime


class SimulatedCrash(Exception):
    pass


def _build_graph(counts: dict[str, int], crash_on: str):
    g = Graph("pipeline")
    node_defs = {
        "a": (lambda inputs: 1, ()),
        "b": (lambda inputs: inputs["out_a"] + 1, ("out_a",)),
        "c": (lambda inputs: inputs["out_b"] * 2, ("out_b",)),
    }
    for nid, (value_fn, inputs) in node_defs.items():

        async def fn(inputs, ctx, _nid=nid, _value_fn=value_fn):
            counts[_nid] = counts.get(_nid, 0) + 1
            if _nid == crash_on and counts[_nid] == 1:
                raise SimulatedCrash(f"simulated crash in {_nid}")
            return {f"out_{_nid}": _value_fn(inputs)}

        g.add_node(
            Node(
                id=nid,
                fn=fn,
                inputs=inputs,
                outputs=(f"out_{nid}",),
                retry=RetryPolicy(max_attempts=1),
            )
        )
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    return g


def test_crash_mid_run_resume_completes_without_recomputing(tmp_path):
    counts: dict[str, int] = {}
    store = CheckpointStore(str(tmp_path / "checkpoints.sqlite3"))

    # Run 1: node b crashes on its first attempt -> run fails, a is done.
    g = _build_graph(counts, crash_on="b")
    first = asyncio.run(AsyncRuntime(g, checkpoint=store, run_id="run-1").run())
    assert first.status == "failed"
    assert counts == {"a": 1, "b": 1}
    assert store.get_run_status("run-1") == "failed"
    assert store.load_nodes("run-1")["a"].status == "completed"
    assert store.load_nodes("run-1")["a"].outputs == {"out_a": 1}

    # Run 2 (resume): a must NOT re-execute; b retries and completes; c runs.
    g2 = _build_graph(counts, crash_on="b")
    second = asyncio.run(AsyncRuntime(g2, checkpoint=store, run_id="run-1").run(resume=True))
    assert second.status == "completed"
    assert second.outputs["out_c"] == 4  # (1 + 1) * 2
    assert counts["a"] == 1, "completed node was re-executed on resume"
    assert counts["b"] == 2, "failed node should execute exactly once more"
    assert counts["c"] == 1
    assert store.get_run_status("run-1") == "completed"


def test_skipped_nodes_stay_skipped_across_resume(tmp_path):
    counts: dict[str, int] = {}
    store = CheckpointStore(str(tmp_path / "checkpoints2.sqlite3"))

    async def boom(inputs, ctx):
        counts["boom"] = counts.get("boom", 0) + 1
        raise RuntimeError("dead")

    async def side(inputs, ctx):
        counts["side"] = counts.get("side", 0) + 1
        return {"side_out": 1}

    async def orphan(inputs, ctx):
        counts["orphan"] = counts.get("orphan", 0) + 1
        return {"orphan_out": 1}

    g = Graph("skip")
    g.add_node(Node(id="boom", fn=boom, outputs=("never",), retry=RetryPolicy(max_attempts=1)))
    g.add_node(Node(id="dependent", fn=orphan, inputs=("never",)))
    g.add_node(Node(id="side", fn=side, outputs=("side_out",)))
    g.add_edge("boom", "dependent")

    first = asyncio.run(AsyncRuntime(g, checkpoint=store, run_id="r").run())
    assert first.status == "failed"
    assert first.node_status["dependent"] == "skipped"
    assert counts["side"] == 1

    g2 = Graph("skip")
    g2.add_node(Node(id="boom", fn=boom, outputs=("never",), retry=RetryPolicy(max_attempts=1)))
    g2.add_node(Node(id="dependent", fn=orphan, inputs=("never",)))
    g2.add_node(Node(id="side", fn=side, outputs=("side_out",)))
    g2.add_edge("boom", "dependent")

    second = asyncio.run(AsyncRuntime(g2, checkpoint=store, run_id="r").run(resume=True))
    assert second.status == "failed"
    assert second.node_status["dependent"] == "skipped"
    assert counts["side"] == 1, "completed node re-executed on resume"
    assert counts["boom"] == 2
