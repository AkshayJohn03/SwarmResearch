"""Graph spec: cycle detection, channel wiring, topological order."""

from __future__ import annotations

import asyncio

import pytest

from swarm.orchestra.graph import CycleError, Graph, GraphError, Node, RetryPolicy


def noop_node(node_id: str, **kwargs) -> Node:
    async def fn(inputs, ctx):
        return {"out": 1}

    return Node(id=node_id, fn=fn, **kwargs)


def test_topological_order_respects_edges():
    g = Graph("t")
    for nid in ["a", "b", "c", "d"]:
        g.add_node(noop_node(nid))
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("b", "d")
    g.add_edge("c", "d")
    order = g.topological_order()
    assert set(order) == {"a", "b", "c", "d"}
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("a") < order.index("c") < order.index("d")


def test_cycle_detection_reports_path():
    g = Graph("t")
    for nid in ["a", "b", "c"]:
        g.add_node(noop_node(nid))
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")
    with pytest.raises(CycleError) as excinfo:
        g.validate()
    assert excinfo.value.path[0] == excinfo.value.path[-1]

    # self-loops are rejected at edge-construction time
    with pytest.raises(CycleError):
        g.add_edge("a", "a")


def test_required_input_must_have_producer():
    g = Graph("t")
    g.add_node(noop_node("a", inputs=("missing_channel",)))
    with pytest.raises(GraphError, match="no producer"):
        g.validate()


def test_duplicate_node_id_rejected():
    g = Graph("t")
    g.add_node(noop_node("a"))
    with pytest.raises(GraphError, match="duplicate"):
        g.add_node(noop_node("a"))


def test_unknown_edge_endpoints_rejected():
    g = Graph("t")
    g.add_node(noop_node("a"))
    with pytest.raises(GraphError, match="unknown node"):
        g.add_edge("a", "ghost")


def test_retry_policy_backoff_is_exponential_with_jitter_bounds():
    policy = RetryPolicy(base_delay_ms=100.0, multiplier=2.0, jitter_ms=0.0)
    assert policy.delay_for(1) == pytest.approx(0.1)
    assert policy.delay_for(3) == pytest.approx(0.4)
    bounded = RetryPolicy(base_delay_ms=100.0, multiplier=2.0, jitter_ms=50.0)
    for _ in range(20):
        assert 0.05 <= bounded.delay_for(1) <= 0.15


def test_entry_nodes_and_producers():
    g = Graph("t")
    g.add_node(noop_node("a", outputs=("ch",)))
    g.add_node(noop_node("b", inputs=("ch",)))
    g.add_edge("a", "b")
    g.validate()
    assert g.entry_nodes() == ["a"]
    assert g.producers() == {"ch": ["a"]}


def _run(coro):
    return asyncio.run(coro)
