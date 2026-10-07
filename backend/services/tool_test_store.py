"""Inspector extension tables in the Agent Runtime database.

Tests have their own lifecycle and are never queued to the Agent run worker.
Inputs stay ephemeral; only input hashes, bounded results and safe events persist.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.models.tool_test import ToolTestRun
from backend.services.tool_management_service import ToolManagementError


class ToolTestStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tool_test_runs (
                run_id TEXT PRIMARY KEY, tool_id TEXT NOT NULL, request_key TEXT NOT NULL,
                input_hash TEXT NOT NULL, created_at TEXT NOT NULL, run_json TEXT NOT NULL,
                UNIQUE(tool_id, request_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS tool_test_events (
                run_id TEXT NOT NULL REFERENCES tool_test_runs(run_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY(run_id,seq))""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS tool_test_history ON tool_test_runs(tool_id,created_at)"
            )

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, tool_id, run_id):
        with self.transaction() as db:
            row = db.execute(
                "SELECT run_json FROM tool_test_runs WHERE run_id=? AND tool_id=?",
                (run_id, tool_id),
            ).fetchone()
        return ToolTestRun.model_validate_json(row[0]) if row else None

    def find(self, tool_id, key, digest):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM tool_test_runs WHERE tool_id=? AND request_key=?",
                (tool_id, key),
            ).fetchone()
        if row is None:
            return None
        if row["input_hash"] != digest:
            raise ToolManagementError(
                "idempotency_conflict",
                "Request ID was already used with different input.",
                409,
            )
        return ToolTestRun.model_validate_json(row["run_json"])

    def claim(self, run, key, digest):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM tool_test_runs WHERE tool_id=? AND request_key=?",
                (run.tool_id, key),
            ).fetchone()
            if row:
                if row["input_hash"] != digest:
                    raise ToolManagementError(
                        "idempotency_conflict",
                        "Request ID was already used with different input.",
                        409,
                    )
                return ToolTestRun.model_validate_json(row["run_json"]), False
            db.execute(
                "INSERT INTO tool_test_runs VALUES(?,?,?,?,?,?)",
                (
                    run.test_run_id,
                    run.tool_id,
                    key,
                    digest,
                    run.created_at,
                    self._json(run),
                ),
            )
            self._event(db, run, "created")
            return run, True

    def save(self, run):
        with self.transaction() as db:
            row = db.execute(
                "SELECT run_json FROM tool_test_runs WHERE run_id=?", (run.test_run_id,)
            ).fetchone()
            previous = ToolTestRun.model_validate_json(row[0]) if row else None
            db.execute(
                "UPDATE tool_test_runs SET run_json=? WHERE run_id=?",
                (self._json(run), run.test_run_id),
            )
            if previous is None or (previous.status, previous.execution_state) != (
                run.status,
                run.execution_state,
            ):
                self._event(
                    db,
                    run,
                    run.status
                    if previous is None or previous.status != run.status
                    else "execution_state",
                )

    @staticmethod
    def _json(run):
        return run.model_copy(update={"approval_summary": None}).model_dump_json()

    @staticmethod
    def _event(db, run, kind):
        seq = db.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM tool_test_events WHERE run_id=?",
            (run.test_run_id,),
        ).fetchone()[0]
        # Deliberately exclude arguments, document text, command output and error messages.
        event = {
            "seq": seq,
            "type": kind,
            "test_run_id": run.test_run_id,
            "tool_call_id": run.tool_call_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "execution_state": run.execution_state,
            "at": run.updated_at,
            "elapsed_ms": run.elapsed_ms,
            "error_code": run.error.get("code") if run.error else None,
        }
        db.execute(
            "INSERT INTO tool_test_events VALUES(?,?,?)",
            (run.test_run_id, seq, json.dumps(event)),
        )

    def events(self, run_id, after=0):
        with self.transaction() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT event_json FROM tool_test_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 200",
                    (run_id, after),
                )
            ]

    def history(self, tool_id, *, limit=25, before=None):
        stamp, run_id = None, ""
        if before:
            try:
                identity, stamp, run_id = json.loads(
                    base64.urlsafe_b64decode(before).decode()
                )
                if (
                    identity != tool_id
                    or not isinstance(stamp, str)
                    or not isinstance(run_id, str)
                ):
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ToolManagementError(
                    "invalid_cursor", "Invalid history cursor."
                ) from exc
        with self.transaction() as db:
            rows = db.execute(
                "SELECT run_id,run_json FROM tool_test_runs WHERE tool_id=? AND (? IS NULL OR created_at < ? OR (created_at=? AND run_id<?)) ORDER BY created_at DESC,run_id DESC LIMIT ?",
                (tool_id, stamp, stamp, stamp, run_id, limit + 1),
            ).fetchall()
        runs = [
            ToolTestRun.model_validate_json(row["run_json"]) for row in rows[:limit]
        ]
        cursor = (
            base64.urlsafe_b64encode(
                json.dumps(
                    [tool_id, runs[-1].created_at, runs[-1].test_run_id]
                ).encode()
            ).decode()
            if len(rows) > limit
            else None
        )
        return {
            "items": [
                r.model_dump(exclude={"result", "approval_summary"}) for r in runs
            ],
            "next_cursor": cursor,
        }

    def recover(self):
        with self.transaction() as db:
            rows = list(db.execute("SELECT run_json FROM tool_test_runs"))
            for row in rows:
                run = ToolTestRun.model_validate_json(row[0])
                if not run.finished_at:
                    active = run.execution_state == "running"
                    stamp = datetime.now(UTC).isoformat()
                    run = run.model_copy(
                        update={
                            "status": "interrupted",
                            "execution_state": "unknown" if active else "stopped",
                            "finished_at": stamp,
                            "updated_at": stamp,
                            "approval_id": None,
                            "approval_summary": None,
                            "error": {
                                "code": "process_restarted",
                                "message": "Process restarted; no execution or approval was replayed.",
                            },
                        }
                    )
                    db.execute(
                        "UPDATE tool_test_runs SET run_json=? WHERE run_id=?",
                        (run.model_dump_json(), run.test_run_id),
                    )
                    self._event(db, run, "interrupted")

    def prune(self):
        removed = []
        cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        with self.transaction() as db:
            kept = 0
            for row in list(
                db.execute(
                    "SELECT run_id,run_json,created_at FROM tool_test_runs ORDER BY created_at DESC"
                )
            ):
                run = ToolTestRun.model_validate_json(row["run_json"])
                if run.finished_at and run.execution_state == "stopped":
                    kept += 1
                    if kept > 100 or row["created_at"] < cutoff:
                        db.execute(
                            "DELETE FROM tool_test_runs WHERE run_id=?",
                            (row["run_id"],),
                        )
                        removed.append(row["run_id"])
        return removed
