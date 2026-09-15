"""Sidecar reliability metadata for structured research memory.

Research Memory is derived from Research Notes.  This store records only the
source revision used for an extraction so freshness can be checked without
changing the Stage 17.1 Claim–Evidence–Entity–Relation schema.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.infrastructure.paths import writable_config_dir

DEFAULT_RESEARCH_MEMORY_RELIABILITY_FILENAME = "research_memory_reliability.sqlite3"
RESEARCH_MEMORY_RELIABILITY_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, *, limit: int = 0) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit]
    return text


@dataclass(frozen=True, slots=True)
class ResearchMemorySourceRevision:
    workspace_id: str
    note_id: str
    source_fingerprint: str
    recorded_at: str


class ResearchMemoryReliabilityStore:
    """Persist replaceable source-revision metadata for structured memory."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else writable_config_dir() / DEFAULT_RESEARCH_MEMORY_RELIABILITY_FILENAME
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_memory_source_revisions (
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, note_id)
            );

            CREATE INDEX IF NOT EXISTS idx_memory_source_revisions_workspace
                ON research_memory_source_revisions(workspace_id, recorded_at DESC);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(RESEARCH_MEMORY_RELIABILITY_SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
        except (OSError, sqlite3.Error):
            # Reliability metadata is derived and must never block app startup.
            return

    def record_source_revision(
        self,
        *,
        workspace_id: object,
        note_id: object,
        source_fingerprint: object,
    ) -> ResearchMemorySourceRevision:
        workspace = _clean(workspace_id, limit=128)
        note = _clean(note_id, limit=128)
        fingerprint = _clean(source_fingerprint, limit=256)
        if not workspace or not note:
            raise ValueError("Research-memory source revision requires workspace_id and note_id.")
        recorded_at = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    connection.execute(
                        """
                        INSERT INTO research_memory_source_revisions(
                            workspace_id, note_id, source_fingerprint, recorded_at
                        ) VALUES(?, ?, ?, ?)
                        ON CONFLICT(workspace_id, note_id) DO UPDATE SET
                            source_fingerprint = excluded.source_fingerprint,
                            recorded_at = excluded.recorded_at
                        """,
                        (workspace, note, fingerprint, recorded_at),
                    )
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to persist research-memory source revision.") from exc
        return ResearchMemorySourceRevision(
            workspace_id=workspace,
            note_id=note,
            source_fingerprint=fingerprint,
            recorded_at=recorded_at,
        )

    def get_source_revision(
        self,
        *,
        workspace_id: object,
        note_id: object,
    ) -> ResearchMemorySourceRevision | None:
        workspace = _clean(workspace_id, limit=128)
        note = _clean(note_id, limit=128)
        if not workspace or not note:
            return None
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    """
                    SELECT workspace_id, note_id, source_fingerprint, recorded_at
                    FROM research_memory_source_revisions
                    WHERE workspace_id = ? AND note_id = ?
                    """,
                    (workspace, note),
                ).fetchone()
        except (OSError, sqlite3.Error):
            return None
        if row is None:
            return None
        return ResearchMemorySourceRevision(
            workspace_id=str(row[0]),
            note_id=str(row[1]),
            source_fingerprint=str(row[2] or ""),
            recorded_at=str(row[3] or ""),
        )

    def delete_source_revision(self, *, workspace_id: object, note_id: object) -> bool:
        workspace = _clean(workspace_id, limit=128)
        note = _clean(note_id, limit=128)
        if not workspace or not note:
            return False
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    cursor = connection.execute(
                        """
                        DELETE FROM research_memory_source_revisions
                        WHERE workspace_id = ? AND note_id = ?
                        """,
                        (workspace, note),
                    )
                    return cursor.rowcount > 0
        except (OSError, sqlite3.Error):
            return False


__all__ = [
    "DEFAULT_RESEARCH_MEMORY_RELIABILITY_FILENAME",
    "RESEARCH_MEMORY_RELIABILITY_SCHEMA_VERSION",
    "ResearchMemoryReliabilityStore",
    "ResearchMemorySourceRevision",
]
