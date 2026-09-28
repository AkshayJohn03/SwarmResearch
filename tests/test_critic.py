"""CriticAgent: coverage gating, span verification, re-tasking plan."""

from __future__ import annotations

import asyncio

from swarm.agents.analyst import AnalystAgent
from swarm.agents.critic import CriticAgent
from swarm.agents.planner import PlannerAgent
from swarm.schemas import ClaimRecord


def make_claim(claim_id: str, doc_id: str, task_id: str, quote: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        doc_id=doc_id,
        doc_title=f"Title {doc_id}",
        quote=quote,
        char_start=2,
        char_end=2 + len(quote),
        sentence=quote,
        salience=0.7,
        task_id=task_id,
    )


def test_low_coverage_triggers_retasking(settings):
    async def scenario():
        plan = await PlannerAgent(settings).plan("the research question")
        search_ids = [t.id for t in plan.search_tasks()]
        claims = [make_claim("c1", "doc-01", search_ids[0], "The XK-7 module is the flagship unit.")]
        analysis = await AnalystAgent(settings).analyze(claims, plan)
        critic = CriticAgent(settings)
        return await critic.review(analysis, plan, docs_text={})

    decision = asyncio.run(scenario())
    assert decision.route == "gapfill"
    assert decision.coverage < settings.coverage_threshold
    assert len(decision.retask.new_tasks) >= 1
    assert all(t.kind.value == "gapfill" for t in decision.retask.new_tasks)


def test_full_coverage_finalizes_without_retasking(settings, backend):
    async def scenario():
        plan = await PlannerAgent(settings).plan("the research question")
        search_ids = [t.id for t in plan.search_tasks()]
        claims = [
            make_claim(
                f"c{i}",
                "doc-01",
                task_id,
                f"Verified evidence sentence number {i} about topic area {i} exists here.",
            )
            for i, task_id in enumerate(search_ids)
        ]
        analysis = await AnalystAgent(settings).analyze(claims, plan)
        docs_text = {d.doc_id: f'xx{d.text[:200]}' for d in backend.docs}
        # make the span check pass: adjust claims to point at real text
        fixed = []
        for c in analysis.claims:
            text = docs_text[c.doc_id]
            quote = text[10:80]
            fixed.append(
                c.model_copy(
                    update={
                        "quote": quote,
                        "char_start": 10,
                        "char_end": 10 + len(quote),
                        "sentence": quote,
                    }
                )
            )
        analysis = analysis.model_copy(update={"claims": fixed})
        critic = CriticAgent(settings)
        return await critic.review(analysis, plan, docs_text=docs_text)

    decision = asyncio.run(scenario())
    assert decision.route == "finalize"
    assert decision.coverage == 1.0
    assert decision.retask.new_tasks == []
    assert decision.unsupported_claims == []


def test_unsupported_claims_fail_span_verification(settings):
    async def scenario():
        plan = await PlannerAgent(settings).plan("the research question")
        search_ids = [t.id for t in plan.search_tasks()]
        claims = [
            make_claim(
                f"c{i}",
                "doc-01",
                task_id,
                f"Fabricated statement variant {i} that is not present anywhere in the source.",
            )
            for i, task_id in enumerate(search_ids)
        ]
        analysis = await AnalystAgent(settings).analyze(claims, plan)
        docs_text = {"doc-01": "totally different text"}
        critic = CriticAgent(settings)
        return await critic.review(analysis, plan, docs_text=docs_text)

    decision = asyncio.run(scenario())
    assert len(decision.unsupported_claims) == 4
    assert decision.route == "gapfill"
