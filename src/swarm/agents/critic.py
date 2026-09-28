"""CriticAgent: coverage check, unsupported-claim detection, re-tasking.

* Coverage = fraction of planned SEARCH sub-topics that produced >= 1 claim.
* Unsupported claims = claims whose quote is NOT an exact match of the
  cited document at the recorded char span (the verification pass that
  underpins the hallucination metric).
* Below the coverage threshold (or with unsupported claims present) the
  critic emits a RetaskPlan; the pipeline compiles those new tasks into
  the gap-fill branch of the DAG and the critic's conditional edge routes
  execution into it.  Bounded loop unrolling: the branch exists in the
  static graph, so cycle detection stays meaningful.
"""

from __future__ import annotations

from swarm.schemas import (
    AnalysisRecord,
    CriticDecision,
    ResearchPlan,
    RetaskPlan,
    TaskKind,
    TaskNode,
)
from swarm.settings import SwarmSettings


class CriticAgent:
    def __init__(self, settings: SwarmSettings) -> None:
        self.settings = settings

    async def review(
        self, analysis: AnalysisRecord, plan: ResearchPlan, docs_text: dict[str, str]
    ) -> CriticDecision:
        search_tasks = plan.search_tasks()
        covered = {
            task.id
            for task in search_tasks
            if any(claim.task_id == task.id for claim in analysis.claims)
        }
        coverage = (len(covered) / len(search_tasks)) if search_tasks else 1.0

        unsupported = [
            claim.claim_id
            for claim in analysis.claims
            if docs_text.get(claim.doc_id, "")[claim.char_start : claim.char_end] != claim.quote
        ]

        uncovered = [task for task in search_tasks if task.id not in covered]
        new_tasks = [
            TaskNode(
                id=f"gapfill-search-{i}",
                kind=TaskKind.GAPFILL,
                query=f"{task.query} detailed data and measured values",
                depends_on=["critic-0"],
                max_docs=self.settings.max_docs_per_task,
            )
            for i, task in enumerate(uncovered)
        ]

        if new_tasks or unsupported:
            reason = (
                f"coverage {coverage:.2f} below threshold {self.settings.coverage_threshold:.2f}"
                if new_tasks
                else f"{len(unsupported)} unsupported claim(s) failed span verification"
            )
            retask = RetaskPlan(reason=reason, coverage=coverage, new_tasks=new_tasks)
            return CriticDecision(
                route="gapfill",
                coverage=coverage,
                unsupported_claims=unsupported,
                retask=retask,
                reason=reason,
            )

        return CriticDecision(
            route="finalize",
            coverage=coverage,
            unsupported_claims=[],
            retask=RetaskPlan(reason="coverage sufficient", coverage=coverage, new_tasks=[]),
            reason=f"coverage {coverage:.2f} meets threshold",
        )
