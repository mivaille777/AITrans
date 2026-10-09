"""Bounded SQLite history; retaining source and logs is explicitly opt-in."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta, UTC
from contextlib import closing
from pathlib import Path
from backend.models.sandbox_debug import SandboxDebugTrace


class SandboxHistoryStore:
    def __init__(self, path: Path, max_runs: int):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_runs = max_runs
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, started TEXT NOT NULL, terminal INTEGER NOT NULL, trace TEXT NOT NULL, owner TEXT NOT NULL)"
            )
            db.execute(
                "DELETE FROM runs WHERE terminal=1 AND started < ?",
                ((datetime.now(UTC) - timedelta(days=30)).isoformat(),),
            )

    def load(self) -> list[tuple[SandboxDebugTrace, dict]]:
        records = []
        with closing(sqlite3.connect(self.path)) as db:
            for raw, owner in db.execute(
                "SELECT trace,owner FROM (SELECT * FROM runs ORDER BY started DESC LIMIT ?) ORDER BY started",
                (self.max_runs + 4,),
            ):
                try:
                    records.append(
                        (SandboxDebugTrace.model_validate_json(raw), json.loads(owner))
                    )
                except (ValueError, TypeError):
                    continue
        return records

    def save(self, trace: SandboxDebugTrace, owner: dict, *, terminal: bool) -> None:
        saved = (
            trace
            if trace.logs_retained
            else trace.model_copy(update={"stdout": "", "stderr": "", "code": None})
        )
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                (
                    trace.run.sandbox_id,
                    trace.run.started_at,
                    int(terminal),
                    saved.model_dump_json(),
                    json.dumps(owner),
                ),
            )
            db.execute(
                "DELETE FROM runs WHERE terminal=1 AND id NOT IN (SELECT id FROM runs ORDER BY started DESC LIMIT ?)",
                (self.max_runs,),
            )
            db.execute(
                "DELETE FROM runs WHERE terminal=1 AND started < ?",
                ((datetime.now(UTC) - timedelta(days=30)).isoformat(),),
            )
