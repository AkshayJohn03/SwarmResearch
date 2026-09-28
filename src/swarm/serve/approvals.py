"""Audited human approvals for the HumanInterrupt flow.

When a node pauses a run on :class:`~swarm.orchestra.human.HumanInterrupt`,
the serving layer opens an approval request here instead of leaving the
pause invisible. Every request and every decision is appended to an
append-only JSONL audit log (``audit_log.jsonl`` — opened in ``"a"`` mode
per write, never truncated, never rewritten) with the fields:

    ts, actor, action, approval_id, node_id, decision, reason

An approval decides exactly once: a second :meth:`ApprovalStore.decide`
raises :class:`ApprovalAlreadyDecided`, which the API surfaces as 409.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DECISIONS = ("approve", "reject")


class ApprovalAlreadyDecided(Exception):
    """Raised when deciding an approval that already has a verdict."""


class InvalidDecision(ValueError):
    """Raised for decisions outside the approved vocabulary."""


@dataclass
class Approval:
    approval_id: str
    node_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | approved | rejected
    requested_by: str = ""
    requested_at: str = ""
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "node_id": self.node_id,
            "payload": self.payload,
            "status": self.status,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApprovalStore:
    """In-memory approval queue backed by an append-only JSONL audit log."""

    def __init__(self, audit_path: str | Path = "audit_log.jsonl") -> None:
        self.audit_path = Path(audit_path)
        self._approvals: dict[str, Approval] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    # -- audit ---------------------------------------------------------------
    def _append_audit(self, entry: dict[str, Any]) -> None:
        """Append one JSON line. Append-only: the file is never rewritten."""
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _audit_entry(
        *, actor: str, action: str, approval_id: str, node_id: str,
        decision: str | None = None, reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ts": _now(),
            "actor": actor,
            "action": action,
            "approval_id": approval_id,
            "node_id": node_id,
            "decision": decision,
            "reason": reason,
        }

    # -- queue ---------------------------------------------------------------
    def request_approval(self, node_id: str, payload: dict[str, Any], requested_by: str) -> str:
        """Open a pending approval and audit it. Returns the approval_id."""
        approval_id = uuid.uuid4().hex
        record = Approval(
            approval_id=approval_id,
            node_id=node_id,
            payload=dict(payload),
            requested_by=requested_by,
            requested_at=_now(),
        )
        with self._lock:
            self._approvals[approval_id] = record
            self._order.append(approval_id)
            self._append_audit(
                self._audit_entry(
                    actor=requested_by, action="requested", approval_id=approval_id, node_id=node_id
                )
            )
        return approval_id

    def decide(self, approval_id: str, decision: str, decided_by: str, reason: str = "") -> Approval:
        """Apply the one-and-only verdict and audit it.

        Raises KeyError for unknown ids, InvalidDecision for a bad verdict,
        and ApprovalAlreadyDecided on a second decision (API maps to 409).
        """
        decision = decision.strip().lower()
        if decision not in DECISIONS:
            raise InvalidDecision(f"decision must be one of {DECISIONS}, got {decision!r}")
        with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise KeyError(approval_id)
            if record.status != "pending":
                raise ApprovalAlreadyDecided(
                    f"approval {approval_id} already decided ({record.status})"
                )
            record.status = "approved" if decision == "approve" else "rejected"
            record.decided_by = decided_by
            record.decided_at = _now()
            record.reason = reason
            self._append_audit(
                self._audit_entry(
                    actor=decided_by,
                    action="decided",
                    approval_id=approval_id,
                    node_id=record.node_id,
                    decision=record.status,
                    reason=reason,
                )
            )
        return record

    def get(self, approval_id: str) -> Approval | None:
        return self._approvals.get(approval_id)

    def list(self, status: str | None = None) -> list[Approval]:
        """Approvals in request order, optionally filtered by status."""
        records = [self._approvals[a] for a in self._order]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records


__all__ = [
    "Approval",
    "ApprovalAlreadyDecided",
    "ApprovalStore",
    "DECISIONS",
    "InvalidDecision",
]
