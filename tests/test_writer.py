"""WriterAgent + end-to-end report citation discipline."""

from __future__ import annotations

import re

from swarm.citations.graph import factual_sentences, is_cited, scoped_lines


def test_offline_report_has_zero_uncited_factual_sentences(offline_run):
    report = offline_run.report
    assert report.startswith("# Research report:")
    uncited = [s for s in factual_sentences(report) if not is_cited(s)]
    assert uncited == [], f"uncited factual sentences found: {uncited}"
    assert offline_run.report_model.uncited_factual_sentences == 0
    assert offline_run.report_model.citation_count > 0


def test_report_sources_appendix_binds_doc_ids_and_spans(offline_run, backend):
    report = offline_run.report
    assert "## Sources" in report
    source_lines = [
        line for line in report.splitlines() if re.match(r"^\[\d+\] doc-\d+", line.strip())
    ]
    assert source_lines, "no source appendix entries"
    for line in source_lines:
        match = re.match(r"^\[(\d+)\] (doc-\d+) - .+ \(chars (\d+)-(\d+)\)", line.strip())
        assert match, f"malformed source entry: {line}"
        doc = backend.get(match.group(2))
        start, end = int(match.group(3)), int(match.group(4))
        assert doc.text[start:end], "char span must fall inside the document"


def test_scoping_rules_skip_meta_sources_and_questions():
    report = (
        "# Title\n"
        "\n"
        "_metadata line_\n"
        "\n"
        "## Sources\n"
        "[1] doc-01 - t (chars 0-5)\n"
        "\n"
        "## Open questions\n"
        "- What about this?\n"
    )
    kinds = {scope.kind for scope in scoped_lines(report)}
    assert "body" not in kinds
    assert factual_sentences(report) == []


def test_inference_marker_satisfies_citation_rule():
    sentence = "The analysts infer an unstated relationship here. *(analyst-inference)*"
    assert is_cited(sentence)
    numbered = "Something factual was measured [3]."
    assert is_cited(numbered)
    assert not is_cited("A bare factual claim without any citation.")
