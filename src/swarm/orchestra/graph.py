"""Static graph specification for the SwarmResearch orchestration runtime.

A :class:`Graph` is pure data: nodes with typed input/output channels,
retry policies, timeouts, and optional conditional routing functions.
The executor in :mod:`swarm.orchestra.runtime` runs it; this module only
builds and validates it.

Design notes
------------
* Channels are the only data path between nodes: a node's declared
  ``inputs`` must be produced by some other node (checked at build time),
  which makes accidental "stringly typed" wiring impossible.
* Conditional edges: a node may carry a ``router`` that inspects its own
  result and returns the successor ids allowed to run.  Edges to other
  successors never fire, so unrouted branches are skipped at runtime
  while remaining visible to static cycle detection.
* Cycles are rejected at build time -- this runtime is a DAG executor by
  design (bounded loop unrolling instead of implicit re-entry; see the
  README "Design decisions" section).
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from swarm.orchestra.runtime import RunContext

NodeFn = Callable[[dict[str, Any], "RunContext"], Awaitable[Any]]
RouterFn = Callable[[Any], Sequence[str]]


class GraphError(RuntimeError):
    """Invalid graph specification."""


class CycleError(GraphError):
    """The graph contains a dependency cycle; ``path`` shows the loop."""

    def __init__(self, path: list[str]) -> None:
        self.path = path
        super().__init__("cycle detected: " + " -> ".join(path))


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with jitter, applied per node."""

    max_attempts: int = 3
    base_delay_ms: float = 25.0
    multiplier: float = 2.0
    jitter_ms: float = 10.0

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        rng = rng or random.Random()
        delay = self.base_delay_ms * (self.multiplier ** (attempt - 1))
        jittered = delay + rng.uniform(-self.jitter_ms, self.jitter_ms)
        return max(0.0, jittered) / 1000.0


@dataclass
class Node:
    """One executable unit in the graph.

    ``fn`` receives ``(inputs, ctx)`` where ``inputs`` maps every declared
    input channel to its value (optional inputs included only when
    present) and returns either a dict keyed by ``outputs`` or, for a
    single-output node, a bare value.
    """

    id: str
    fn: NodeFn
    inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_ms: float | None = None
    router: RouterFn | None = None
    stage: str = "task"
    description: str = ""


class Graph:
    """Directed acyclic graph of :class:`Node` objects with typed channels."""

    def __init__(self, name: str = "graph") -> None:
        self.name = name
        self._nodes: dict[str, Node] = {}
        self._succ: dict[str, set[str]] = {}
        self._pred: dict[str, set[str]] = {}

    # -- construction ---------------------------------------------------

    def add_node(self, node: Node) -> Node:
        if node.id in self._nodes:
            raise GraphError(f"duplicate node id: {node.id}")
        self._nodes[node.id] = node
        self._succ[node.id] = set()
        self._pred[node.id] = set()
        return node

    def add_edge(self, src: str, dst: str) -> None:
        if src not in self._nodes or dst not in self._nodes:
            raise GraphError(f"edge references unknown node: {src} -> {dst}")
        if src == dst:
            raise CycleError([src, dst])
        self._succ[src].add(dst)
        self._pred[dst].add(src)

    # -- accessors ------------------------------------------------------

    @property
    def nodes(self) -> dict[str, Node]:
        return self._nodes

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def successors(self, node_id: str) -> set[str]:
        return set(self._succ[node_id])

    def predecessors(self, node_id: str) -> set[str]:
        return set(self._pred[node_id])

    def entry_nodes(self) -> list[str]:
        return [nid for nid in self._nodes if not self._pred[nid]]

    def producers(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for node in self._nodes.values():
            for channel in node.outputs:
                out.setdefault(channel, []).append(node.id)
        return out

    # -- validation -----------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`GraphError` on bad wiring; detect cycles statically."""
        producers = self.producers()
        for node in self._nodes.values():
            for channel in node.inputs:
                if channel not in producers:
                    raise GraphError(
                        f"node {node.id}: required input channel '{channel}' has no producer"
                    )
                if node.id in producers[channel]:
                    raise GraphError(f"node {node.id} produces its own input '{channel}'")
        self._check_cycles()

    def _check_cycles(self) -> None:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self._nodes}
        for start in self._nodes:
            if color[start] != WHITE:
                continue
            color[start] = GRAY
            path = [start]
            stack: list[tuple[str, Any]] = [(start, iter(self._succ[start]))]
            while stack:
                vertex, edge_iter = stack[-1]
                advanced = False
                for nxt in edge_iter:
                    if color[nxt] == GRAY:
                        idx = path.index(nxt)
                        raise CycleError([*path[idx:], nxt])
                    if color[nxt] == WHITE:
                        color[nxt] = GRAY
                        path.append(nxt)
                        stack.append((nxt, iter(self._succ[nxt])))
                        advanced = True
                        break
                if not advanced:
                    color[vertex] = BLACK
                    path.pop()
                    stack.pop()

    def topological_order(self) -> list[str]:
        """Kahn's algorithm; raises :class:`CycleError` if none exists."""
        indegree = {nid: len(self._pred[nid]) for nid in self._nodes}
        ready = sorted(nid for nid, deg in indegree.items() if deg == 0)
        order: list[str] = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for succ in sorted(self._succ[nid]):
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    ready.append(succ)
        if len(order) != len(self._nodes):
            raise CycleError(["<graph>"])
        return order
