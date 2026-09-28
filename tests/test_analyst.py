"""AnalystAgent: jaccard dedupe, contradiction detection, gap notes."""

from __future__ import annotations

import asyncio

import pytest

from swarm.agents.analyst import AnalystAgent
from swarm.agents.planner import PlannerAgent
from swarm.schemas import ClaimRecord


def claim(
    claim_id: str,
    doc_id: str,
    sentence: str,
    entity: str,
    attribute: str,
    value: str,
    salience: float = 0.8,
    task_id: str = "search-0",
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        doc_id=doc_id,
        doc_title=f"Title {doc_id}",
        quote=sentence,
        char_start=0,
        char_end=len(sentence),
        sentence=sentence,
        entity=entity,
        attribute=attribute,
        value=value,
        salience=salience,
        task_id=task_id,
    )


@pytest.fixture()
def analyst(settings) -> AnalystAgent:
    return AnalystAgent(settings)


@pytest.fixture()
def plan(settings):
    return asyncio.run(PlannerAgent(settings).plan("the research query"))


def test_numeric_contradiction_detected(analyst, plan):
    c1 = claim("c1", "doc-02", "Spec sheet sentence about noise.", "XK-7 compressor module", "noise", "47 dB(A)")
    c2 = claim("c2", "doc-03", "Lab report sentence about noise.", "XK-7 compressor module", "noise", "42 dB(A)")
    analysis = asyncio.run(analyst.analyze([c1, c2], plan))
    assert analysis.contradictions, "numeric mismatch was not flagged"
    contradiction = analysis.contradictions[0]
    assert contradiction.kind == "numeric_mismatch"
    assert contradiction.entity == "XK-7 compressor module"
    assert contradiction.attribute == "noise"
    assert {contradiction.left.value, contradiction.right.value} == {"47 dB(A)", "42 dB(A)"}
    assert {contradiction.left.doc_id, contradiction.right.doc_id} == {"doc-02", "doc-03"}


def test_no_contradiction_when_values_agree(analyst, plan):
    c1 = claim("c1", "doc-02", "One statement.", "XK-7 compressor module", "noise", "42 dB(A)")
    c2 = claim("c2", "doc-03", "Another statement.", "XK-7 compressor module", "noise", "42 dB(A)")
    analysis = asyncio.run(analyst.analyze([c1, c2], plan))
    assert analysis.contradictions == []


def test_negation_conflict_for_boolean_attributes(analyst, plan):
    c1 = claim("c1", "doc-13", "The warranty covers the module.", "Kaltwerk", "warranty", "7 years")
    c2 = claim("c2", "doc-42", "The warranty does not cover the module.", "Kaltwerk", "warranty", "7 years")
    analysis = asyncio.run(analyst.analyze([c1, c2], plan))
    kinds = {c.kind for c in analysis.contradictions}
    assert "negation_conflict" in kinds


def test_duplicate_claims_collapse_via_jaccard(analyst, plan):
    sentence = (
        "The XK-7 compressor module registered a sound pressure level of 42 dB(A) "
        "at three metres inside the chamber."
    )
    c1 = claim("c1", "doc-03", sentence, "XK-7 compressor module", "noise", "42 dB(A)", salience=0.9)
    c2 = claim("c2", "doc-03", sentence, "XK-7 compressor module", "noise", "42 dB(A)", salience=0.5)
    analysis = asyncio.run(analyst.analyze([c1, c2], plan))
    assert len(analysis.claims) == 1
    assert analysis.dropped_duplicates == 1
    assert analysis.claims[0].salience == pytest.approx(0.9)


def test_gap_notes_for_uncovered_subtopics(analyst, plan):
    search_ids = [t.id for t in plan.search_tasks()]
    claims = [
        claim("c1", "doc-01", "A relevant sentence about the query topic.", "", "", "", 0.5, task_id=search_ids[0])
    ]
    analysis = asyncio.run(analyst.analyze(claims, plan))
    assert len(analysis.gaps) == len(search_ids) - 1
    assert all("no claims extracted" in g.reason for g in analysis.gaps)
    assert analysis.entities == []
