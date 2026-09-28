"""Async task-graph executor.

Execution semantics
-------------------
* A node is scheduled when (a) every required input channel is available
  in the channel store, and (b) at least one incoming edge has "fired"
  (entry nodes need no fired edge).
* Conditional edges: a node carrying a ``router`` returns the successor
  ids allowed to run; edges to other successors never fire, so unrouted
  branches stay pending and are marked ``skipped`` when the graph
  settles.  Static cycle detection still sees every candidate edge.
* Per-node timeout (``asyncio.wait_for``) and retry with exponential
  backoff + jitter; exhausted retries are unrecoverable.
* Cancellation propagation: when a node fails unrecoverably, every
  transitive successor whose producers all failed/skipped is marked
  ``skipped`` without executing.
* Checkpointing: each terminal node state is persisted; ``run(resume=True)``
  restores outputs and fired edges so finished nodes are never re-executed.
* Human-in-the-loop: a node raising :class:`HumanInterrupt` pauses the
  run (siblings cancelled and rewound to pending); resume re-executes
  only the paused node with the injected answer.
* Observability: a typed event bus (NodeStarted/NodeFinished/NodeFailed/
  NodeSkipped/NodePaused/GraphCompleted) plus a ``span_sink`` hook that
  receives ForensiQ-compatible span dicts after every attempt.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from swarm.orchestra.checkpoint import CheckpointStore
from swarm.orchestra.graph import Graph, Node
from swarm.orchestra.human import HumanInputQueue, HumanInputSource, HumanInterrupt
from swarm.settings import SwarmSettings


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
@dataclass
class NodeStarted:
    run_id: str
    node_id: str
    attempt: int
    sequence: int = 0


@dataclass
class NodeFinished:
    run_id: str
    node_id: str
    attempt: int
    duration_ms: float
    outputs: list[str]
    sequence: int = 0


@dataclass
class NodeFailed:
    run_id: str
    node_id: str
    attempt: int
    error: str
    recoverable: bool
    sequence: int = 0


@dataclass
class NodeSkipped:
    run_id: str
    node_id: str
    reason: str
    sequence: int = 0


@dataclass
class NodePaused:
    run_id: str
    node_id: str
    prompt: str
    sequence: int = 0


@dataclass
class GraphCompleted:
    run_id: str
    status: str  # "completed" | "failed" | "paused"
    duration_ms: float
    error: str | None = None
    sequence: int = 0


RuntimeEvent = (
    NodeStarted | NodeFinished | NodeFailed | NodeSkipped | NodePaused | GraphCompleted
)

SpanDict = dict[str, Any]
SpanSink = Callable[[SpanDict], None]


class EventBus:
    """Tiny typed pub/sub; sync subscribers run inline, async ones scheduled."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[RuntimeEvent], Any]] = []
        self._sequence = 0

    def subscribe(self, callback: Callable[[RuntimeEvent], Any]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: RuntimeEvent) -> None:
        event.sequence = self._sequence
        self._sequence += 1
        loop = asyncio.get_event_loop()
        for callback in self._subscribers:
            result = callback(event)
            if asyncio.iscoroutine(result):
                loop.create_task(result)


@dataclass
class RunContext:
    """What a node function may touch.  Deliberately small."""

    run_id: str
    node_id: str
    blackboard: Any
    llm: Any
    settings: SwarmSettings
    human: HumanInputSource
    runtime: AsyncRuntime


@dataclass
class RunResult:
    run_id: str
    status: str
    outputs: dict[str, Any]
    events: list[RuntimeEvent]
    spans: list[SpanDict]
    node_status: dict[str, str]
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class _Outcome:
    kind: str  # "completed" | "failed" | "paused"
    outputs: dict[str, Any] = field(default_factory=dict)
    fired: list[str] = field(default_factory=list)
    attempts: int = 0
    error: str | None = None
    prompt: str = ""


class AsyncRuntime:
    """Executes a :class:`Graph` as an asyncio task graph."""

    def __init__(
        self,
        graph: Graph,
        *,
        settings: SwarmSettings | None = None,
        llm: Any = None,
        blackboard: Any = None,
        event_bus: EventBus | None = None,
        checkpoint: CheckpointStore | None = None,
        span_sink: SpanSink | None = None,
        max_concurrency: int = 4,
        human_source: HumanInputSource | None = None,
        revive: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.graph = graph
        self.settings = settings or SwarmSettings()
        self.llm = llm
        self.blackboard = blackboard
        self.event_bus = event_bus or EventBus()
        self.checkpoint = checkpoint
        self.span_sink = span_sink
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._human_source: HumanInputSource = human_source or HumanInputQueue()
        self._revive = revive
        self._run_id = run_id
        self._rng = random.Random()

        self._channel_store: dict[str, Any] = {}
        self._node_status: dict[str, str] = {}
        self._fired_edges: set[tuple[str, str]] = set()
        self._events: list[RuntimeEvent] = []
        self._spans: list[SpanDict] = []
        self._attempts: dict[str, int] = {}

    # -- public API --------------------------------------------------------

    async def run(self, *, resume: bool = False, human_input: str | None = None) -> RunResult:
        self.graph.validate()
        run_id = self._run_id or uuid.uuid4().hex[:12]
        self._run_id = run_id

        if human_input is not None:
            if isinstance(self._human_source, HumanInputQueue):
                self._human_source.push(human_input)
            else:
                self._human_source = HumanInputQueue([human_input])

        for node_id in self.graph.nodes:
            self._node_status[node_id] = "pending"
        if resume:
            if self.checkpoint is None:
                raise ValueError("resume requires a CheckpointStore")
            self._restore(run_id)
        elif self.checkpoint is not None:
            self.checkpoint.create_run(run_id, self.graph.name)

        started = time.perf_counter()
        failure: str | None = None
        paused = False

        running: dict[asyncio.Task, str] = {}
        try:
            self._schedule_ready(running)
            while running:
                done, _ = await asyncio.wait(set(running), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task not in running:
                        continue  # cancelled by a pause rewind earlier in this batch
                    node_id = running.pop(task)
                    outcome: _Outcome = task.result()
                    if outcome.kind == "completed":
                        self._node_status[node_id] = "completed"
                        self._channel_store.update(outcome.outputs)
                        for dst in outcome.fired:
                            self._fired_edges.add((node_id, dst))
                        if self.checkpoint:
                            self.checkpoint.save_node(
                                run_id,
                                node_id,
                                "completed",
                                outcome.attempts,
                                outcome.outputs,
                                outcome.fired,
                            )
                    elif outcome.kind == "failed":
                        self._node_status[node_id] = "failed"
                        failure = outcome.error
                        if self.checkpoint:
                            self.checkpoint.save_node(run_id, node_id, "failed", outcome.attempts)
                        for skip_id in self._blocked_downstream(node_id):
                            self._mark_skipped(run_id, skip_id, "upstream failure")
                    else:  # paused
                        self._node_status[node_id] = "paused"
                        paused = True
                        if self.checkpoint:
                            self.checkpoint.save_node(run_id, node_id, "paused", outcome.attempts)
                            self.checkpoint.save_pause(
                                run_id, node_id, outcome.prompt, {"run_id": run_id}
                            )
                        await self._rewind_siblings(run_id, running)
                        running.clear()
                if not paused:
                    self._schedule_ready(running)
        finally:
            if not paused:
                for node_id, status in list(self._node_status.items()):
                    if status == "pending":
                        self._mark_skipped(run_id, node_id, "branch not routed or upstream failed")

        final_status = "paused" if paused else ("failed" if failure else "completed")
        duration_ms = (time.perf_counter() - started) * 1000.0
        error = failure if failure else ("run paused awaiting human input" if paused else None)
        self._publish(
            GraphCompleted(run_id=run_id, status=final_status, duration_ms=duration_ms, error=error)
        )
        if self.checkpoint:
            self.checkpoint.set_run_status(run_id, final_status)
        return RunResult(
            run_id=run_id,
            status=final_status,
            outputs=dict(self._channel_store),
            events=list(self._events),
            spans=list(self._spans),
            node_status=dict(self._node_status),
            error=error,
            duration_ms=duration_ms,
        )

    # -- scheduling --------------------------------------------------------

    def _schedule_ready(self, running: dict[asyncio.Task, str]) -> None:
        for node_id, status in self._node_status.items():
            if status != "pending" or node_id in running.values():
                continue
            if not self._is_ready(node_id):
                continue
            task = asyncio.create_task(self._execute_node(node_id))
            running[task] = node_id

    def _is_ready(self, node_id: str) -> bool:
        node = self.graph.node(node_id)
        preds = self.graph.predecessors(node_id)
        if preds and not any((src, node_id) in self._fired_edges for src in preds):
            return False
        return all(channel in self._channel_store for channel in node.inputs)

    # -- execution ---------------------------------------------------------

    async def _execute_node(self, node_id: str) -> _Outcome:
        # The semaphore bounds how many nodes execute concurrently (fan-out cap).
        async with self._semaphore:
            return await self._run_node_attempts(node_id)

    async def _run_node_attempts(self, node_id: str) -> _Outcome:
        node = self.graph.node(node_id)
        run_id = self._run_id or ""
        attempts = 0
        while attempts < max(1, node.retry.max_attempts):
            attempts += 1
            self._attempts[node_id] = attempts
            self._publish(NodeStarted(run_id=run_id, node_id=node_id, attempt=attempts))
            span_start = time.perf_counter()
            try:
                inputs: dict[str, Any] = {c: self._channel_store[c] for c in node.inputs}
                for channel in node.optional_inputs:
                    if channel in self._channel_store:
                        inputs[channel] = self._channel_store[channel]
                ctx = RunContext(
                    run_id=run_id,
                    node_id=node_id,
                    blackboard=self.blackboard,
                    llm=self.llm,
                    settings=self.settings,
                    human=self._human_source,
                    runtime=self,
                )
                coro = node.fn(inputs, ctx)
                if node.timeout_ms is not None:
                    result = await asyncio.wait_for(coro, node.timeout_ms / 1000.0)
                else:
                    result = await coro
                outputs = self._bind_outputs(node, result)
                fired = self._route(node, result)
                duration_ms = (time.perf_counter() - span_start) * 1000.0
                self._publish(
                    NodeFinished(
                        run_id=run_id,
                        node_id=node_id,
                        attempt=attempts,
                        duration_ms=duration_ms,
                        outputs=list(outputs),
                    )
                )
                self._emit_span(node, attempts, "ok", duration_ms)
                return _Outcome(kind="completed", outputs=outputs, fired=fired, attempts=attempts)
            except HumanInterrupt as interrupt:
                duration_ms = (time.perf_counter() - span_start) * 1000.0
                self._publish(
                    NodePaused(run_id=run_id, node_id=node_id, prompt=interrupt.prompt)
                )
                self._emit_span(node, attempts, "paused", duration_ms)
                return _Outcome(kind="paused", attempts=attempts, prompt=interrupt.prompt)
            except asyncio.CancelledError:
                self._emit_span(node, attempts, "cancelled", (time.perf_counter() - span_start) * 1000.0)
                raise
            except Exception as exc:  # noqa: BLE001 - runtime boundary, error is typed into events
                duration_ms = (time.perf_counter() - span_start) * 1000.0
                recoverable = attempts < max(1, node.retry.max_attempts)
                self._publish(
                    NodeFailed(
                        run_id=run_id,
                        node_id=node_id,
                        attempt=attempts,
                        error=f"{type(exc).__name__}: {exc}",
                        recoverable=recoverable,
                    )
                )
                self._emit_span(node, attempts, "error", duration_ms, attrs={"error": str(exc)})
                if not recoverable:
                    return _Outcome(kind="failed", attempts=attempts, error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(node.retry.delay_for(attempts, self._rng))
        return _Outcome(kind="failed", attempts=attempts, error="unreachable")

    def _bind_outputs(self, node: Node, result: Any) -> dict[str, Any]:
        if not node.outputs:
            return {}
        if isinstance(result, dict):
            missing = [c for c in node.outputs if c not in result]
            if missing:
                raise RuntimeError(f"node {node.id} did not produce outputs: {missing}")
            return {c: result[c] for c in node.outputs}
        if len(node.outputs) == 1:
            return {node.outputs[0]: result}
        raise RuntimeError(f"node {node.id} returned a bare value but declares {len(node.outputs)} outputs")

    def _route(self, node: Node, result: Any) -> list[str]:
        successors = self.graph.successors(node.id)
        if node.router is not None:
            chosen = list(node.router(result))
            unknown = [dst for dst in chosen if dst not in successors]
            if unknown:
                raise RuntimeError(f"router of {node.id} returned non-successors: {unknown}")
            return chosen
        return sorted(successors)

    # -- failure / pause handling -------------------------------------------

    def _blocked_downstream(self, failed_id: str) -> list[str]:
        """Transitive successors whose producers have all failed/been skipped."""
        skipped: list[str] = []
        stack = list(self.graph.successors(failed_id))
        seen: set[str] = set()
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            preds = self.graph.predecessors(node_id)
            if preds and all(
                self._node_status.get(p) in {"failed", "skipped"} for p in preds
            ):
                self._node_status[node_id] = "skipped"
                skipped.append(node_id)
                stack.extend(self.graph.successors(node_id))
        return skipped

    def _mark_skipped(self, run_id: str, node_id: str, reason: str) -> None:
        self._node_status[node_id] = "skipped"
        self._publish(NodeSkipped(run_id=run_id, node_id=node_id, reason=reason))
        if self.checkpoint:
            self.checkpoint.save_node(run_id, node_id, "skipped")

    async def _rewind_siblings(self, run_id: str, running: dict[asyncio.Task, str]) -> None:
        """On pause: cancel in-flight siblings and rewind them to pending."""
        if not running:
            return
        tasks = list(running)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for node_id in running.values():
            self._node_status[node_id] = "pending"
            if self.checkpoint:
                self.checkpoint.save_node(run_id, node_id, "pending")

    # -- resume ---------------------------------------------------------------

    def _restore(self, run_id: str) -> None:
        assert self.checkpoint is not None
        records = self.checkpoint.load_nodes(run_id)
        for node_id, record in records.items():
            if node_id not in self._node_status:
                continue
            if record.status == "completed":
                self._node_status[node_id] = "completed"
                outputs = record.outputs
                if self._revive is not None:
                    outputs = self._revive(node_id, outputs)
                self._channel_store.update(outputs)
                for dst in record.fired:
                    self._fired_edges.add((node_id, dst))
            else:
                # failed, paused AND skipped nodes re-enter the scheduler:
                # a resume re-derives routing; only completed work is reused.
                self._node_status[node_id] = "pending"

    # -- observability ----------------------------------------------------------

    def _publish(self, event: RuntimeEvent) -> None:
        self._events.append(event)
        self.event_bus.publish(event)

    def _emit_span(
        self,
        node: Node,
        attempt: int,
        status: str,
        duration_ms: float,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        span: SpanDict = {
            "span_id": uuid.uuid4().hex,
            "parent_id": f"run-{self._run_id}",
            "name": f"node:{node.id}",
            "stage": node.stage,
            "duration_ms": round(duration_ms, 3),
            "status": status,
            "attrs": {"attempt": attempt, **(attrs or {})},
        }
        self._spans.append(span)
        if self.span_sink is not None:
            try:
                self.span_sink(span)
            except Exception:  # noqa: BLE001 - observability must never break execution
                pass
