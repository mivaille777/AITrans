"""Human review state for the Stage 19 Evidence Ledger.

Stage 20 deliberately keeps reviewer judgement separate from Stage 19 machine
validation. A reviewer can accept a claim, but later provenance revalidation can
still make that claim stale or insufficient and therefore ineligible for
literature synthesis.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.infrastructure.paths import writable_config_dir
from app.research.evidence_ledger import DEFAULT_EVIDENCE_LEDGER_FILENAME

REVIEW_STATUSES = frozenset({"unreviewed", "accepted", "rejected", "needs_review"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, *, limit: int = 0) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit] if limit > 0 and len(text) > limit else text


@dataclass(frozen=True, slots=True)
class EvidenceReviewRecord:
    entry_id: str
    workspace_id: str
    status: str
    note: str
    reviewed_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class EvidenceReviewHistoryRecord:
    history_id: str
    entry_id: str
    workspace_id: str
    status: str
    note: str
    reviewed_at: str


class EvidenceReviewStore:
    """Persist current reviewer judgement plus append-only change history."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else writable_config_dir() / DEFAULT_EVIDENCE_LEDGER_FILENAME
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
            CREATE TABLE IF NOT EXISTS evidence_ledger_reviews (
                entry_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unreviewed',
                note TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_ledger_review_history (
                history_id TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ledger_reviews_workspace
                ON evidence_ledger_reviews(workspace_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ledger_review_history_entry
                ON evidence_ledger_review_history(entry_id, reviewed_at DESC);
            """
        )

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
        except (OSError, sqlite3.Error):
            return

    @staticmethod
    def _row_to_review(row: tuple[object, ...]) -> EvidenceReviewRecord:
        return EvidenceReviewRecord(
            entry_id=str(row[0]),
            workspace_id=str(row[1]),
            status=str(row[2]),
            note=str(row[3] or ""),
            reviewed_at=str(row[4]),
            updated_at=str(row[5]),
        )

    def get(self, *, workspace_id: object, entry_id: object) -> EvidenceReviewRecord | None:
        workspace = _clean(workspace_id, limit=128)
        identifier = _clean(entry_id, limit=128)
        if not workspace or not identifier:
            return None
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    """
                    SELECT entry_id, workspace_id, status, note, reviewed_at, updated_at
                    FROM evidence_ledger_reviews
                    WHERE workspace_id = ? AND entry_id = ?
                    """,
                    (workspace, identifier),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence review storage is unavailable.") from exc
        return self._row_to_review(row) if row is not None else None

    def list_for_workspace(self, *, workspace_id: object) -> tuple[EvidenceReviewRecord, ...]:
        workspace = _clean(workspace_id, limit=128)
        if not workspace:
            return ()
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                rows = connection.execute(
                    """
                    SELECT entry_id, workspace_id, status, note, reviewed_at, updated_at
                    FROM evidence_ledger_reviews
                    WHERE workspace_id = ?
                    ORDER BY updated_at DESC, entry_id ASC
                    """,
                    (workspace,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence review storage is unavailable.") from exc
        return tuple(self._row_to_review(row) for row in rows)

    def set_review(
        self,
        *,
        workspace_id: object,
        entry_id: object,
        status: object,
        note: object = "",
    ) -> EvidenceReviewRecord:
        workspace = _clean(workspace_id, limit=128)
        identifier = _clean(entry_id, limit=128)
        review_status = _clean(status, limit=32)
        review_note = _clean(note, limit=4000)
        if not workspace or not identifier:
            raise ValueError("Evidence review requires workspace and entry IDs.")
        if review_status not in REVIEW_STATUSES:
            raise ValueError("Invalid Evidence review status.")

        current = self.get(workspace_id=workspace, entry_id=identifier)
        if current is not None and current.status == review_status and current.note == review_note:
            return current

        now = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    connection.execute(
                        """
                        INSERT INTO evidence_ledger_reviews(
                            entry_id, workspace_id, status, note, reviewed_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        ON CONFLICT(entry_id) DO UPDATE SET
                            workspace_id = excluded.workspace_id,
                            status = excluded.status,
                            note = excluded.note,
                            reviewed_at = excluded.reviewed_at,
                            updated_at = excluded.updated_at
                        """,
                        (identifier, workspace, review_status, review_note, now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO evidence_ledger_review_history(
                            history_id, entry_id, workspace_id, status, note, reviewed_at
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (uuid4().hex, identifier, workspace, review_status, review_note, now),
                    )
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence review storage is unavailable.") from exc
        return EvidenceReviewRecord(
            entry_id=identifier,
            workspace_id=workspace,
            status=review_status,
            note=review_note,
            reviewed_at=now,
            updated_at=now,
        )

    def history_count(self, *, entry_id: object) -> int:
        identifier = _clean(entry_id, limit=128)
        if not identifier:
            return 0
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT COUNT(*) FROM evidence_ledger_review_history WHERE entry_id = ?",
                    (identifier,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence review storage is unavailable.") from exc
        return int(row[0] or 0) if row else 0


__all__ = [
    "EvidenceReviewHistoryRecord",
    "EvidenceReviewRecord",
    "EvidenceReviewStore",
    "REVIEW_STATUSES",
]
