"""Crash-resilient run state backed by stdlib sqlite3 (WAL mode).

The runtime persists one row per node per run: status, attempt count, the
node's declared outputs (JSON) and the edges its completion fired.  A
crashed or failed run can therefore be resumed without re-executing any
node that already completed -- a stronger guarantee than "re-run the
whole graph" and the core of the resume test in the suite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    graph_name TEXT NOT NULL,
    status     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS node_runs (
    run_id       TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    status       TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    outputs_json TEXT NOT NULL DEFAULT '{}',
    fired_json   TEXT NOT NULL DEFAULT '[]',
    updated_at   REAL NOT NULL,
    PRIMARY KEY (run_id, node_id)
);
CREATE TABLE IF NOT EXISTS pauses (
    run_id       TEXT PRIMARY KEY,
    node_id      TEXT NOT NULL,
    question     TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL
);
"""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return str(obj)


@dataclass
class NodeRecord:
    node_id: str
    status: str
    attempts: int = 0
    outputs: dict[str, Any] = field(default_factory=dict)
    fired: list[str] = field(default_factory=list)


class CheckpointStore:
    """Durable key/value store over runs and node states."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        path_str = str(path)
        self._conn = sqlite3.connect(path_str, isolation_level=None)
        if path_str != ":memory:":
            # WAL lets a crashed process leave a consistent, recoverable db.
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # -- runs ------------------------------------------------------------

    def create_run(self, run_id: str, graph_name: str) -> None:
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, graph_name, status, created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, graph_name, now, now),
        )

    def set_run_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, time.time(), run_id),
        )

    def get_run_status(self, run_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row[0] if row else None

    # -- node states -----------------------------------------------------

    def save_node(
        self,
        run_id: str,
        node_id: str,
        status: str,
        attempts: int = 0,
        outputs: dict[str, Any] | None = None,
        fired: list[str] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO node_runs "
            "(run_id, node_id, status, attempts, outputs_json, fired_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                node_id,
                status,
                attempts,
                json.dumps(outputs or {}, default=_json_default),
                json.dumps(fired or []),
                time.time(),
            ),
        )

    def load_nodes(self, run_id: str) -> dict[str, NodeRecord]:
        rows = self._conn.execute(
            "SELECT node_id, status, attempts, outputs_json, fired_json "
            "FROM node_runs WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {
            row[0]: NodeRecord(
                node_id=row[0],
                status=row[1],
                attempts=row[2],
                outputs=json.loads(row[3]),
                fired=json.loads(row[4]),
            )
            for row in rows
        }

    # -- human pauses ------------------------------------------------------

    def save_pause(self, run_id: str, node_id: str, question: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO pauses (run_id, node_id, question, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, node_id, question, json.dumps(payload, default=_json_default), time.time()),
        )

    def load_pause(self, run_id: str) -> tuple[str, str, dict] | None:
        row = self._conn.execute(
            "SELECT node_id, question, payload_json FROM pauses WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return row[0], row[1], json.loads(row[2])

    def close(self) -> None:
        self._conn.close()
