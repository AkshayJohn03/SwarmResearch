"""Citation metrics: hallucination_rate and citation_coverage."""

from __future__ import annotations

from swarm.citations.graph import CitationGraph


def test_offline_run_has_zero_hallucination_rate(offline_run, backend):
    docs_text = {d.doc_id: d.text for d in backend.docs}
    metrics = CitationGraph.claim_metrics(offline_run.blackboard.claims, docs_text)
    assert metrics["total_claims"] > 0
    assert metrics["valid_claims"] == metrics["total_claims"]
    assert metrics["hallucination_rate"] == 0.0
    assert offline_run.metrics["hallucination_rate"] == 0.0


def test_fabricated_span_counts_as_hallucination(backend):
    docs_text = {d.doc_id: d.text for d in backend.docs}

    real = offline_style_claim(docs_text)
    fabricated = real.model_copy(
        update={"char_start": 0, "char_end": 30, "quote": "completely fabricated words here"},
        deep=True,
    )
    metrics = CitationGraph.claim_metrics([real, fabricated], docs_text)
    assert metrics["hallucination_rate"] == 0.5


def offline_style_claim(docs_text):
    from swarm.schemas import ClaimRecord

    doc_id = next(iter(docs_text))
    text = docs_text[doc_id]
    start = text.find(". ") + 2
    end = text.find(".", start) + 1
    return ClaimRecord(
        claim_id="c-real",
        doc_id=doc_id,
        doc_title="t",
        quote=text[start:end],
        char_start=start,
        char_end=end,
        sentence=text[start:end],
        salience=0.5,
    )


def test_citation_coverage_is_one_for_offline_report(offline_run):
    assert offline_run.metrics["citation_coverage"] == 1.0


def test_empty_claims_yield_zero_hallucination_rate():
    assert CitationGraph.claim_metrics([], {})["hallucination_rate"] == 0.0
