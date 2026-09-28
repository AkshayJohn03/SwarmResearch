"""PlannerAgent: research query -> typed DAG of TaskNodes.

Offline mode uses deterministic decomposition heuristics (four focused
sub-queries per user query).  With a real LLM configured the planner asks
for sub-queries as JSON but *always* falls back to the heuristics on any
parse failure -- planning must never be the reason a run dies.
"""

from __future__ import annotations

import json
import logging

from swarm.llm import EchoMockClient, LLMClient, Message
from swarm.schemas import ResearchPlan, TaskKind, TaskNode
from swarm.settings import SwarmSettings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You decompose research questions into focused web/document search sub-queries. "
    "Reply with ONLY a JSON array of 3-5 strings, no prose."
)


class PlannerAgent:
    def __init__(self, settings: SwarmSettings, llm: LLMClient | None = None) -> None:
        self.settings = settings
        self.llm = llm

    def _use_llm(self) -> bool:
        return (
            not self.settings.offline
            and self.llm is not None
            and not isinstance(self.llm, EchoMockClient)
        )

    async def plan(self, query: str) -> ResearchPlan:
        subtopics = self._heuristic_subtopics(query)
        if self._use_llm():
            subtopics = await self._llm_subtopics(query) or subtopics

        per_task_budget = max(200, self.settings.token_budget // max(1, len(subtopics)))
        tasks: list[TaskNode] = []
        for i, subtopic in enumerate(subtopics):
            search_id = f"search-{i}"
            read_id = f"read-{i}"
            tasks.append(
                TaskNode(
                    id=search_id,
                    kind=TaskKind.SEARCH,
                    query=subtopic,
                    depends_on=["plan"],
                    max_docs=self.settings.max_docs_per_task,
                    max_tokens=per_task_budget,
                )
            )
            tasks.append(
                TaskNode(
                    id=read_id,
                    kind=TaskKind.READ,
                    query=subtopic,
                    depends_on=[search_id],
                    max_docs=self.settings.max_docs_per_task,
                    max_tokens=per_task_budget,
                )
            )
        analyze_deps = [f"read-{i}" for i in range(len(subtopics))]
        tasks.append(
            TaskNode(
                id="analyze-0",
                kind=TaskKind.ANALYZE,
                query=query,
                depends_on=analyze_deps,
                max_tokens=self.settings.token_budget,
            )
        )
        tasks.append(
            TaskNode(id="critic-0", kind=TaskKind.CRITIC, query=query, depends_on=["analyze-0"])
        )
        tasks.append(
            TaskNode(id="writer-0", kind=TaskKind.WRITE, query=query, depends_on=["merge"])
        )
        return ResearchPlan(query=query, tasks=tasks, total_token_budget=self.settings.token_budget)

    # -- strategies ---------------------------------------------------------

    @staticmethod
    def _heuristic_subtopics(query: str) -> list[str]:
        base = query.strip().rstrip("?").strip() or "the research question"
        return [
            base,
            f"{base} technical specifications and measured data",
            f"{base} field performance reliability and maintenance",
            f"{base} costs standards and regulatory risks",
        ]

    async def _llm_subtopics(self, query: str) -> list[str] | None:
        assert self.llm is not None
        try:
            raw = await self.llm.complete(
                [
                    Message(role="system", content=_SYSTEM_PROMPT),
                    Message(role="user", content=query),
                ],
                temperature=0.2,
            )
            start, end = raw.find("["), raw.rfind("]")
            if start == -1 or end <= start:
                return None
            parsed = json.loads(raw[start : end + 1])
            subtopics = [str(item).strip() for item in parsed if str(item).strip()]
            return subtopics or None
        except Exception as exc:  # noqa: BLE001 - planner must degrade, not crash
            logger.warning("planner LLM sub-topic generation failed, using heuristics: %s", exc)
            return None
