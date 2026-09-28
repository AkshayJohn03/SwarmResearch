"""Audited human approvals: queue, append-only JSONL audit trail, one verdict.

Covers the store contract (request -> audit line -> decide -> second audit
line, exactly-once decision) and the HTTP surface (GET /approvals?status=,
POST /approvals/{id}/decision with 409 on re-decision).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from swarm.app import create_app
from swarm.serve.approvals import (
    ApprovalAlreadyDecided,
    ApprovalStore,
    InvalidDecision,
)


def _read_audit(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_request_then_decision_appends_two_audit_lines(tmp_path):
    audit = tmp_path / "audit_log.jsonl"
    store = ApprovalStore(audit)

    approval_id = store.request_approval(
        node_id="analyze-0", payload={"prompt": "approve the merge?"}, requested_by="serve"
    )
    lines = _read_audit(audit)
    assert len(lines) == 1
    assert lines[0]["action"] == "requested"
    assert lines[0]["approval_id"] == approval_id
    assert lines[0]["node_id"] == "analyze-0"
    assert lines[0]["actor"] == "serve"
    assert lines[0]["decision"] is None
    assert lines[0]["ts"]

    record = store.decide(approval_id, "approve", decided_by="alice", reason="safe to proceed")
    lines = _read_audit(audit)
    assert len(lines) == 2
    assert lines[1]["action"] == "decided"
    assert lines[1]["approval_id"] == approval_id
    assert lines[1]["node_id"] == "analyze-0"
    assert lines[1]["actor"] == "alice"
    assert lines[1]["decision"] == "approved"
    assert lines[1]["reason"] == "safe to proceed"

    assert record.status == "approved"
    assert record.decided_by == "alice"


def test_decision_is_exactly_once(tmp_path):
    store = ApprovalStore(tmp_path / "audit_log.jsonl")
    approval_id = store.request_approval("critic-0", {}, requested_by="serve")

    store.decide(approval_id, "reject", decided_by="bob", reason="coverage too low")
    with pytest.raises(ApprovalAlreadyDecided):
        store.decide(approval_id, "approve", decided_by="alice")
    # the rejected verdict stands; the second attempt was not audited
    assert store.get(approval_id).status == "rejected"
    assert len(_read_audit(tmp_path / "audit_log.jsonl")) == 2


def test_audit_log_is_append_only_never_rewritten(tmp_path):
    audit = tmp_path / "audit_log.jsonl"
    audit.write_text('{"historical": "line-preserved"}\n', encoding="utf-8")
    store = ApprovalStore(audit)

    approval_id = store.request_approval("writer-0", {}, requested_by="serve")
    store.decide(approval_id, "approve", decided_by="carol")
    raw = audit.read_text(encoding="utf-8").splitlines()
    assert raw[0] == '{"historical": "line-preserved"}'
    assert len(raw) == 3


def test_rejected_decision_and_invalid_verdict(tmp_path):
    store = ApprovalStore(tmp_path / "audit_log.jsonl")
    approval_id = store.request_approval("search-0", {}, requested_by="serve")
    record = store.decide(approval_id, "REJECT", decided_by="bob")  # case-insensitive
    assert record.status == "rejected"
    with pytest.raises(InvalidDecision):
        store.decide("x", "maybe", decided_by="bob")


def test_http_decision_surface(tmp_path):
    store = ApprovalStore(tmp_path / "audit_log.jsonl")
    client = TestClient(create_app(approval_store=store))

    approval_id = store.request_approval(
        node_id="analyze-0", payload={"prompt": "proceed?"}, requested_by="serve"
    )

    listing = client.get("/approvals").json()["approvals"]
    assert [a["approval_id"] for a in listing] == [approval_id]
    assert listing[0]["status"] == "pending"

    decided = client.post(
        f"/approvals/{approval_id}/decision",
        json={"decision": "approve", "decided_by": "alice", "reason": "ok"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    replay = client.post(
        f"/approvals/{approval_id}/decision",
        json={"decision": "reject", "decided_by": "bob", "reason": "changed my mind"},
    )
    assert replay.status_code == 409

    assert client.get("/approvals", params={"status": "approved"}).json()["approvals"]
    assert client.get("/approvals", params={"status": "pending"}).json()["approvals"] == []
    missing = client.post(
        "/approvals/unknown-id/decision", json={"decision": "approve", "decided_by": "alice"}
    )
    assert missing.status_code == 404
    bad_verdict = client.post(
        f"/approvals/{approval_id}/decision", json={"decision": "maybe", "decided_by": "alice"}
    )
    assert bad_verdict.status_code == 422

    # exactly two audit lines for this approval: requested + decided
    lines = _read_audit(tmp_path / "audit_log.jsonl")
    assert [line["action"] for line in lines if line["approval_id"] == approval_id] == [
        "requested",
        "decided",
    ]
