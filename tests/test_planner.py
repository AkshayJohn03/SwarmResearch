"""PlannerAgent: deterministic offline decomposition into a typed DAG plan."""

from __future__ import annotations

import asyncio

from swarm.agents.planner import PlannerAgent
from swarm.llm import EchoMockClient
from swarm.schemas import TaskKind


def test_plan_contains_full_task_dag(settings):
    plan = asyncio.run(_plan(settings))
    kinds = [t.kind for t in plan.tasks]
    assert kinds.count(TaskKind.SEARCH) >= 3
    assert kinds.count(TaskKind.SEARCH) == kinds.count(TaskKind.READ)
    assert TaskKind.ANALYZE in kinds and TaskKind.CRITIC in kinds and TaskKind.WRITE in kinds

    ids = {t.id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.depends_on:
            if dep in ids:
                assert dep in ids, f"{task.id} depends on unknown {dep}"
    # read tasks depend on their search task
    for task in plan.tasks:
        if task.kind == TaskKind.READ:
            search_id = task.depends_on[0]
            assert any(t.id == search_id and t.kind == TaskKind.SEARCH for t in plan.tasks)


async def _plan(settings):
    return await PlannerAgent(settings, EchoMockClient()).plan(
        "How reliable is the XK-7 compressor module?"
    )


def test_search_tasks_carry_budgets(settings):
    plan = asyncio.run(_plan(settings))
    for task in plan.search_tasks():
        assert task.max_docs == settings.max_docs_per_task
        assert task.max_tokens > 0
    assert plan.total_token_budget == settings.token_budget


def test_heuristic_subtopics_are_query_specific(settings):
    plan = asyncio.run(_plan(settings))
    queries = [t.query for t in plan.search_tasks()]
    assert any("reliable" in q for q in queries)
    assert len(set(queries)) == len(queries), "sub-topic queries must be distinct"


def test_offline_planner_never_calls_llm(settings):
    llm = EchoMockClient()
    asyncio.run(PlannerAgent(settings, llm).plan("anything"))
    assert llm.calls == 0
