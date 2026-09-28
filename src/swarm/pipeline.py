"""ResearchPipeline: plan -> compile DAG -> execute -> report + metrics.

This is where the agents and the runtime meet.  The planner's TaskNodes
are compiled 1:1 into runtime graph nodes; a critic-controlled gap-fill
branch (search -> read -> analyze) plus a passthrough node implement
bounded re-tasking as pure conditional routing, so the executed graph is
always a statically-validated DAG.

Channels:
    plan | hits_search-i | claims_read-i | analysis | decision | retask
    | critic_analysis | branch_analysis (passthrough OR gapfill-analyze)
    | analysis_final (merge) | report | report_model
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from swarm.agents.analyst import AnalystAgent
from swarm.agents.critic import CriticAgent
from swarm.agents.planner import PlannerAgent
from swarm.agents.reader import ReaderAgent
from swarm.agents.search import SearchBackend, select_backend
from swarm.agents.writer import WriterAgent
from swarm.citations.graph import CitationGraph
from swarm.llm import EchoMockClient, LLMClient
from swarm.memory.blackboard import Blackboard
from swarm.memory.compress import ContextCompressor
from swarm.orchestra.checkpoint import CheckpointStore
from swarm.orchestra.graph import Graph, Node
from swarm.orchestra.runtime import AsyncRuntime, EventBus, RunResult, RuntimeEvent, SpanDict
from swarm.schemas import (
    AnalysisRecord,
    ClaimRecord,
    CriticDecision,
    ResearchPlan,
    SearchHit,
    TaskKind,
    TaskNode,
    WrittenReport,
)
from swarm.settings import SwarmSettings


@dataclass
class ResearchRunResult:
    run_id: str
    status: str
    query: str
    report: str
    report_model: WrittenReport | None
    analysis: AnalysisRecord | None
    plan: ResearchPlan
    metrics: dict[str, float]
    events: list[RuntimeEvent]
    spans: list[SpanDict]
    node_status: dict[str, str]
    blackboard: Blackboard


class ResearchPipeline:
    def __init__(
        self,
        settings: SwarmSettings | None = None,
        *,
        llm: LLMClient | None = None,
        backend: SearchBackend | None = None,
        checkpoint: CheckpointStore | None = None,
        event_bus: EventBus | None = None,
        span_sink: Any = None,
    ) -> None:
        self.settings = settings or SwarmSettings()
        if llm is not None:
            self.llm = llm
        else:
            self.llm = EchoMockClient() if self.settings.offline else None
        self.backend = backend or select_backend(self.settings)
        self.checkpoint = checkpoint
        self.event_bus = event_bus or EventBus()
        self.span_sink = span_sink

    # -- public ------------------------------------------------------------

    async def run(
        self,
        query: str,
        *,
        run_id: str | None = None,
        resume: bool = False,
        human_input: str | None = None,
    ) -> ResearchRunResult:
        blackboard = Blackboard()
        planner = PlannerAgent(self.settings, self.llm)
        reader = ReaderAgent(self.settings, self.llm, blackboard)
        analyst = AnalystAgent(self.settings)
        critic = CriticAgent(self.settings)
        writer = WriterAgent(self.settings)
        compressor = ContextCompressor(self.settings.token_budget)

        plan = await planner.plan(query)
        graph = self._compile(plan, reader=reader, analyst=analyst, critic=critic, writer=writer, compressor=compressor)

        runtime = AsyncRuntime(
            graph,
            settings=self.settings,
            llm=self.llm,
            blackboard=blackboard,
            event_bus=self.event_bus,
            checkpoint=self.checkpoint,
            span_sink=self.span_sink,
            max_concurrency=self.settings.max_concurrency,
            revive=self._revive,
            run_id=run_id,
        )
        result: RunResult = await runtime.run(resume=resume, human_input=human_input)

        report = str(result.outputs.get("report", ""))
        report_model = result.outputs.get("report_model")
        analysis = result.outputs.get("analysis_final")
        docs_text = {d.doc_id: d.text for d in self.backend.docs}
        metrics: dict[str, float] = CitationGraph.claim_metrics(blackboard.claims, docs_text)
        metrics["citation_coverage"] = round(CitationGraph.report_citation_coverage(report), 6)
        metrics["contradictions"] = float(len(analysis.contradictions)) if analysis else 0.0
        metrics["plan_coverage"] = float(getattr(result.outputs.get("retask"), "coverage", 1.0))
        metrics["compression_ratio"] = float(blackboard.metrics.get("compression_ratio", 1.0))

        return ResearchRunResult(
            run_id=result.run_id,
            status=result.status,
            query=query,
            report=report,
            report_model=report_model if isinstance(report_model, WrittenReport) else None,
            analysis=analysis if isinstance(analysis, AnalysisRecord) else None,
            plan=plan,
            metrics=metrics,
            events=result.events,
            spans=result.spans,
            node_status=result.node_status,
            blackboard=blackboard,
        )

    # -- graph compilation ---------------------------------------------------

    def _compile(
        self,
        plan: ResearchPlan,
        *,
        reader: ReaderAgent,
        analyst: AnalystAgent,
        critic: CriticAgent,
        writer: WriterAgent,
        compressor: ContextCompressor,
    ) -> Graph:
        g = Graph("research")
        read_task_ids = [t.id for t in plan.read_tasks()]
        search_task_ids = [t.id for t in plan.search_tasks()]

        async def plan_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            return {"plan": plan}

        g.add_node(Node(id="plan", fn=plan_fn, outputs=("plan",), stage="plan"))

        for task in plan.search_tasks():
            g.add_node(
                Node(
                    id=task.id,
                    fn=self._make_search_fn(task),
                    inputs=("plan",),
                    outputs=(f"hits_{task.id}",),
                    stage="search",
                )
            )
            g.add_edge("plan", task.id)

        for task in plan.read_tasks():
            search_id = task.depends_on[0]
            g.add_node(
                Node(
                    id=task.id,
                    fn=self._make_read_fn(task, search_id, reader),
                    inputs=(f"hits_{search_id}",),
                    outputs=(f"claims_{task.id}",),
                    stage="read",
                )
            )
            g.add_edge(search_id, task.id)

        analyze_inputs = tuple(f"claims_{rid}" for rid in read_task_ids) + ("plan",)

        async def analyze_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            merged: list[ClaimRecord] = []
            for rid in read_task_ids:
                merged.extend(inputs.get(f"claims_{rid}", []))
            kept, stats = compressor.compress_claims(merged)
            ctx.blackboard.metrics["compression_ratio"] = stats.compression_ratio
            analysis = await analyst.analyze(kept, plan)
            return {"analysis": analysis}

        g.add_node(Node(id="analyze-0", fn=analyze_fn, inputs=analyze_inputs, outputs=("analysis",), stage="analyze"))
        for rid in read_task_ids:
            g.add_edge(rid, "analyze-0")

        async def critic_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            docs_text = {d.doc_id: d.text for d in self.backend.docs}
            decision = await critic.review(inputs["analysis"], plan, docs_text)
            return {"decision": decision, "retask": decision, "critic_analysis": inputs["analysis"]}

        g.add_node(
            Node(
                id="critic-0",
                fn=critic_fn,
                inputs=("analysis", "plan"),
                outputs=("decision", "retask", "critic_analysis"),
                stage="critic",
                router=lambda result: [
                    "gapfill-search-0" if result["decision"].route == "gapfill" else "passthrough"
                ],
            )
        )
        g.add_edge("analyze-0", "critic-0")

        async def passthrough_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            return {"branch_analysis": inputs["critic_analysis"]}

        g.add_node(
            Node(id="passthrough", fn=passthrough_fn, inputs=("critic_analysis",), outputs=("branch_analysis",), stage="route")
        )
        g.add_edge("critic-0", "passthrough")

        # -- bounded gap-fill branch (executed only when the critic routes it)
        g.add_node(
            Node(id="gapfill-search-0", fn=self._make_gapfill_search_fn(), inputs=("retask",), outputs=("gapfill_hits",), stage="gapfill_search")
        )
        g.add_edge("critic-0", "gapfill-search-0")
        g.add_node(
            Node(id="gapfill-read-0", fn=self._make_gapfill_read_fn(reader), inputs=("gapfill_hits", "retask"), outputs=("gapfill_claims",), stage="gapfill_read")
        )
        g.add_edge("gapfill-search-0", "gapfill-read-0")

        async def gapfill_analyze_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            merged = list(inputs["analysis"].claims) + list(inputs["gapfill_claims"])
            analysis = await analyst.analyze(merged, plan)
            return {"branch_analysis": analysis}

        g.add_node(
            Node(id="gapfill-analyze-0", fn=gapfill_analyze_fn, inputs=("gapfill_claims", "analysis"), outputs=("branch_analysis",), stage="gapfill_analyze")
        )
        g.add_edge("gapfill-read-0", "gapfill-analyze-0")

        async def merge_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            return {"analysis_final": inputs["branch_analysis"]}

        g.add_node(
            Node(id="merge", fn=merge_fn, inputs=("analysis", "branch_analysis"), outputs=("analysis_final",), stage="merge")
        )
        g.add_edge("passthrough", "merge")
        g.add_edge("gapfill-analyze-0", "merge")

        async def writer_fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            decision = inputs.get("retask")
            coverage = decision.coverage if isinstance(decision, CriticDecision) else None
            report = await writer.write(
                query=plan.query,
                analysis=inputs["analysis_final"],
                plan=plan,
                retask_coverage=coverage,
                compression_ratio=ctx.blackboard.metrics.get("compression_ratio", 1.0),
            )
            return {"report": report.text, "report_model": report}

        g.add_node(
            Node(id="writer-0", fn=writer_fn, inputs=("analysis_final",), outputs=("report", "report_model"), stage="write")
        )
        g.add_edge("merge", "writer-0")

        _ = search_task_ids  # documented in the channel map above
        return g

    # -- node factories ---------------------------------------------------------

    def _make_search_fn(self, task: TaskNode):
        async def fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            hits = await self.backend.search(task.query, task.max_docs)
            ctx.blackboard.record_task(task.id, {"hits": [h.doc_id for h in hits]})
            return {f"hits_{task.id}": hits}

        return fn

    def _make_read_fn(self, task: TaskNode, search_id: str, reader: ReaderAgent):
        async def fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            hits: list[SearchHit] = inputs[f"hits_{search_id}"]
            claims: list[ClaimRecord] = []
            for hit in hits:
                doc = self.backend.get(hit.doc_id)
                claims.extend(await reader.read(doc, task))
            ctx.blackboard.add_claims(claims)
            return {f"claims_{task.id}": claims}

        return fn

    def _make_gapfill_search_fn(self):
        async def fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            decision: CriticDecision = inputs["retask"]
            hits: list[SearchHit] = []
            seen: set[str] = set()
            for task in decision.retask.new_tasks:
                for hit in await self.backend.search(task.query, task.max_docs):
                    if hit.doc_id not in seen:
                        seen.add(hit.doc_id)
                        hits.append(hit)
            return {"gapfill_hits": hits}

        return fn

    def _make_gapfill_read_fn(self, reader: ReaderAgent):
        async def fn(inputs: dict, ctx) -> dict:  # noqa: ANN001
            decision: CriticDecision = inputs["retask"]
            claims: list[ClaimRecord] = []
            task = TaskNode(
                id="gapfill-read-0",
                kind=TaskKind.READ,
                query=" | ".join(t.query for t in decision.retask.new_tasks),
                max_docs=self.settings.max_docs_per_task,
            )
            for hit in inputs["gapfill_hits"]:
                doc = self.backend.get(hit.doc_id)
                claims.extend(await reader.read(doc, task))
            ctx.blackboard.add_claims(claims)
            return {"gapfill_claims": claims}

        return fn

    # -- checkpoint revival --------------------------------------------------------

    @staticmethod
    def _revive(node_id: str, outputs: dict[str, Any]) -> dict[str, Any]:
        """Re-hydrate pydantic models restored from the checkpoint store."""

        def hits(value: Any) -> Any:
            return [SearchHit.model_validate(v) for v in value] if isinstance(value, list) else value

        def claims(value: Any) -> Any:
            return [ClaimRecord.model_validate(v) for v in value] if isinstance(value, list) else value

        revived: dict[str, Any] = {}
        for key, value in outputs.items():
            if key.startswith("hits_") or key == "gapfill_hits":
                revived[key] = hits(value)
            elif key.startswith("claims_") or key == "gapfill_claims":
                revived[key] = claims(value)
            elif key in {"analysis", "critic_analysis", "branch_analysis", "analysis_final"}:
                revived[key] = AnalysisRecord.model_validate(value)
            elif key in {"decision", "retask"}:
                revived[key] = CriticDecision.model_validate(value)
            elif key == "plan":
                revived[key] = ResearchPlan.model_validate(value)
            elif key == "report_model":
                revived[key] = WrittenReport.model_validate(value)
            else:
                revived[key] = value
        return revived
