"""Transactional local configuration; no tool executors or user documents stored here."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.infrastructure.paths import writable_config_dir
from backend.services.tool_management_service import ToolManagementError


class ToolManagementRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else writable_config_dir() / "tools.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tool_settings
                       (tool_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
                        revision INTEGER NOT NULL, config_json TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self, tool_id):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM tool_settings WHERE tool_id=?", (tool_id,)
            ).fetchone()
        return (
            dict(row)
            if row
            else {"enabled": 1, "revision": 0, "config_json": "{}", "updated_at": None}
        )

    def update(self, tool_id, revision, *, enabled=None, config=None):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM tool_settings WHERE tool_id=?", (tool_id,)
            ).fetchone()
            current = (
                dict(row) if row else {"enabled": 1, "revision": 0, "config_json": "{}"}
            )
            if revision != current["revision"]:
                raise ToolManagementError(
                    "revision_conflict",
                    "Tool configuration changed. Reload and retry.",
                    409,
                )
            db.execute(
                """INSERT INTO tool_settings VALUES(?,?,?,?,?)
                          ON CONFLICT(tool_id) DO UPDATE SET enabled=excluded.enabled,
                          revision=excluded.revision,config_json=excluded.config_json,updated_at=excluded.updated_at""",
                (
                    tool_id,
                    current["enabled"] if enabled is None else int(enabled),
                    revision + 1,
                    current["config_json"] if config is None else json.dumps(config),
                    datetime.now(UTC).isoformat(),
                ),
            )
