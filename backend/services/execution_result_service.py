"""Persist bounded execution receipts alongside conversation messages."""

import json
import sqlite3
from contextlib import closing

from pydantic import ValidationError

from backend.models.execution_results import ExecutionResult
from backend.sandbox.environment import known_secret_environment_values
from backend.services.sandbox_debug_service import _safe_trace_text


def run_execution_results(state) -> list[ExecutionResult]:
    results = []
    for item in state.tool_results:
        if item.get("tool_name") not in {"python_execute", "command_execute"}:
            continue
        data = item.get("data") or {}
        if not data.get("sandbox_id"):
            continue
        secrets = known_secret_environment_values()
        stdout, stderr = str(data.get("stdout", "")), str(data.get("stderr", ""))
        try:
            results.append(
                ExecutionResult(
                    sandbox_id=data["sandbox_id"],
                    tool_call_id=item.get("tool_call_id", ""),
                    status=data.get("status", "failed"),
                    exit_code=data.get("exit_code"),
                    duration_ms=data.get("duration_ms", 0),
                    stdout=_safe_trace_text(stdout, limit=65536, secret_values=secrets),
                    stderr=_safe_trace_text(stderr, limit=65536, secret_values=secrets),
                    logs_truncated=len(stdout) > 65536 or len(stderr) > 65536,
                    source_file_id=data.get("source_file_id", ""),
                    output_files=data.get("output_files", []),
                )
            )
        except (ValidationError, TypeError):
            continue
    return results[-16:]


def _connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "CREATE TABLE IF NOT EXISTS conversation_execution_results (message_id TEXT PRIMARY KEY REFERENCES messages(message_id) ON DELETE CASCADE, receipts TEXT NOT NULL)"
    )
    return db


def save_execution_results(path, message_id: str, results: list[ExecutionResult]):
    with closing(_connect(path)) as db, db:
        db.execute(
            "INSERT OR REPLACE INTO conversation_execution_results VALUES (?,?)",
            (message_id, json.dumps([r.model_dump() for r in results])),
        )


def load_execution_results(path, message_id: str) -> list[ExecutionResult]:
    with closing(_connect(path)) as db:
        row = db.execute(
            "SELECT receipts FROM conversation_execution_results WHERE message_id=?",
            (message_id,),
        ).fetchone()
    if not row:
        return []
    try:
        return [ExecutionResult.model_validate(item) for item in json.loads(row[0])]
    except (ValidationError, ValueError, TypeError):
        return []
