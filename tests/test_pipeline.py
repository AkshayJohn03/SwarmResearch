"""End-to-end offline research pipeline (planner -> runtime -> report)."""

from __future__ import annotations

from swarm.orchestra.runtime import GraphCompleted, NodeFinished, NodeStarted


def test_offline_run_completes_and_surfaces_planted_contradiction(offline_run):
    result = offline_run
    assert result.status == "completed"
    assert result.blackboard.claims, "no claims reached the blackboard"

    # the planted doc-02 (47 dB) vs doc-03 (42 dB) contradiction must surface
    noise_contradictions = [
        c
        for c in result.analysis.contradictions
        if c.attribute == "noise" and "XK-7" in c.entity
    ]
    assert noise_contradictions, "planted contradiction was not detected"
    values = {
        float(c.left.value.split()[0].replace(",", "")) for c in noise_contradictions
    } | {float(c.right.value.split()[0].replace(",", "")) for c in noise_contradictions}
    assert {42.0, 47.0} <= values
    assert "42" in result.report and "47" in result.report
    assert "Conflicting evidence" in result.report
    assert "## Sources" in result.report


def test_offline_run_event_stream_is_ordered_and_complete(offline_run):
    events = offline_run.events
    assert any(isinstance(e, NodeStarted) for e in events)
    assert any(isinstance(e, NodeFinished) for e in events)
    last = events[-1]
    assert isinstance(last, GraphCompleted) and last.status == "completed"

    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences)

    finished_at = {
        e.node_id: i for i, e in enumerate(events) if isinstance(e, NodeFinished)
    }
    started_at = {e.node_id: i for i, e in enumerate(events) if isinstance(e, NodeStarted)}
    for node_id, start_idx in started_at.items():
        if node_id.startswith("read-"):
            search_id = node_id.replace("read-", "search-")
            assert finished_at[search_id] < start_idx
        if node_id == "analyze-0":
            read_finishes = [finished_at[k] for k in finished_at if k.startswith("read-")]
            assert max(read_finishes) < start_idx
        if node_id == "writer-0":
            assert finished_at["merge"] < start_idx


def test_offline_run_nodes_settle_correctly(offline_run):
    status = offline_run.node_status
    assert set(status.values()) <= {"completed", "skipped"}
    for node_id, state in status.items():
        if node_id.startswith("gapfill") or node_id == "passthrough":
            assert state in {"completed", "skipped"}, node_id
    assert status["plan"] == "completed"
    assert status["writer-0"] == "completed"


def test_offline_run_emits_forensiq_compatible_spans(offline_run):
    spans = offline_run.spans
    assert spans
    expected = {"span_id", "parent_id", "name", "stage", "duration_ms", "status", "attrs"}
    for span in spans:
        assert set(span) == expected
        assert isinstance(span["duration_ms"], float)
        assert span["attrs"]["attempt"] >= 1
    stages = {s["stage"] for s in spans}
    assert {"plan", "search", "read", "analyze", "critic", "write"} <= stages


def test_metrics_reported_on_run(offline_run):
    metrics = offline_run.metrics
    assert metrics["hallucination_rate"] == 0.0
    assert metrics["citation_coverage"] == 1.0
    assert metrics["total_claims"] > 0
    assert metrics["contradictions"] >= 1
    assert 0.0 < metrics["compression_ratio"] <= 1.0


def test_report_rendering_rules(offline_run):
    report = offline_run.report
    assert report.startswith("# Research report:")
    assert "- Headline finding:" in report
    assert "## Executive summary" in report
    assert "## Confidence notes" in report
    assert "## Open questions" in report
