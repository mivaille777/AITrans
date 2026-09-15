"""SQLite-backed Evidence Ledger for Research Workspaces.

Stage 19 persists research conclusions separately from Stage 17 structured
memory. Structured memory remains replaceable derived state from Research Notes;
ledger entries only retain stable provenance identifiers back to that memory and
are revalidated against the live source/reliability state before use.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.infrastructure.paths import writable_config_dir

DEFAULT_EVIDENCE_LEDGER_FILENAME = "research_evidence_ledger.sqlite3"
EVIDENCE_LEDGER_SCHEMA_VERSION = 1
DEFAULT_LEDGER_LIMIT = 100
MAX_LEDGER_LIMIT = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_storage_path() -> Path:
    return writable_config_dir() / DEFAULT_EVIDENCE_LEDGER_FILENAME


def _clean(value: object, *, limit: int = 0) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit]
    return text


def _normalized(value: object) -> str:
    return " ".join(_clean(value).casefold().split())


def _bounded_confidence(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True, slots=True)
class EvidenceLedgerLinkDraft:
    role: str
    support_kind: str
    claim_id: str
    relation_id: str
    evidence_id: str
    note_id: str
    document_id: str
    confidence: float = 0.0
    captured_source_status: str = "legacy_unknown"


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEntryRecord:
    entry_id: str
    workspace_id: str
    entry_kind: str
    statement: str
    normalized_statement: str
    origin_kind: str
    origin_id: str
    query: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class EvidenceLedgerLinkRecord:
    link_id: str
    entry_id: str
    role: str
    support_kind: str
    claim_id: str
    relation_id: str
    evidence_id: str
    note_id: str
    document_id: str
    confidence: float
    captured_source_status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceLedgerValidationRecord:
    validation_id: str
    entry_id: str
    status: str
    usable_support_count: int
    usable_conflict_count: int
    supporting_document_count: int
    conflicting_document_count: int
    stale_link_count: int
    missing_link_count: int
    reason_codes: tuple[str, ...]
    checked_at: str


class EvidenceLedgerStore:
    """Persist Claim-centered research conclusions and provenance links."""

    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path) if storage_path is not None else _default_storage_path()
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_ledger_entries (
                entry_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                entry_kind TEXT NOT NULL,
                statement TEXT NOT NULL,
                normalized_statement TEXT NOT NULL,
                origin_kind TEXT NOT NULL DEFAULT '',
                origin_id TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, entry_kind, normalized_statement)
            );

            CREATE TABLE IF NOT EXISTS evidence_ledger_links (
                link_id TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL,
                role TEXT NOT NULL,
                support_kind TEXT NOT NULL,
                claim_id TEXT NOT NULL DEFAULT '',
                relation_id TEXT NOT NULL DEFAULT '',
                evidence_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                captured_source_status TEXT NOT NULL DEFAULT 'legacy_unknown',
                created_at TEXT NOT NULL,
                FOREIGN KEY(entry_id)
                    REFERENCES evidence_ledger_entries(entry_id)
                    ON DELETE CASCADE,
                UNIQUE(entry_id, role, evidence_id, claim_id, relation_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_ledger_validations (
                validation_id TEXT PRIMARY KEY,
                entry_id TEXT NOT NULL,
                status TEXT NOT NULL,
                usable_support_count INTEGER NOT NULL DEFAULT 0,
                usable_conflict_count INTEGER NOT NULL DEFAULT 0,
                supporting_document_count INTEGER NOT NULL DEFAULT 0,
                conflicting_document_count INTEGER NOT NULL DEFAULT 0,
                stale_link_count INTEGER NOT NULL DEFAULT 0,
                missing_link_count INTEGER NOT NULL DEFAULT 0,
                reason_codes_json TEXT NOT NULL DEFAULT '[]',
                checked_at TEXT NOT NULL,
                FOREIGN KEY(entry_id)
                    REFERENCES evidence_ledger_entries(entry_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ledger_entries_workspace
                ON evidence_ledger_entries(workspace_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ledger_links_entry
                ON evidence_ledger_links(entry_id, role);
            CREATE INDEX IF NOT EXISTS idx_ledger_links_note
                ON evidence_ledger_links(note_id);
            CREATE INDEX IF NOT EXISTS idx_ledger_validations_entry
                ON evidence_ledger_validations(entry_id, checked_at DESC);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(EVIDENCE_LEDGER_SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
        except (OSError, sqlite3.Error):
            # The ledger is durable research state but must not prevent startup.
            return

    @staticmethod
    def _row_to_entry(row: tuple[object, ...]) -> EvidenceLedgerEntryRecord:
        return EvidenceLedgerEntryRecord(
            entry_id=str(row[0]),
            workspace_id=str(row[1]),
            entry_kind=str(row[2]),
            statement=str(row[3]),
            normalized_statement=str(row[4]),
            origin_kind=str(row[5] or ""),
            origin_id=str(row[6] or ""),
            query=str(row[7] or ""),
            created_at=str(row[8]),
            updated_at=str(row[9]),
        )

    @staticmethod
    def _row_to_link(row: tuple[object, ...]) -> EvidenceLedgerLinkRecord:
        return EvidenceLedgerLinkRecord(
            link_id=str(row[0]),
            entry_id=str(row[1]),
            role=str(row[2]),
            support_kind=str(row[3]),
            claim_id=str(row[4] or ""),
            relation_id=str(row[5] or ""),
            evidence_id=str(row[6]),
            note_id=str(row[7]),
            document_id=str(row[8]),
            confidence=float(row[9] or 0.0),
            captured_source_status=str(row[10] or "legacy_unknown"),
            created_at=str(row[11]),
        )

    @staticmethod
    def _row_to_validation(row: tuple[object, ...]) -> EvidenceLedgerValidationRecord:
        try:
            raw_codes = json.loads(str(row[9] or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            raw_codes = []
        return EvidenceLedgerValidationRecord(
            validation_id=str(row[0]),
            entry_id=str(row[1]),
            status=str(row[2]),
            usable_support_count=int(row[3] or 0),
            usable_conflict_count=int(row[4] or 0),
            supporting_document_count=int(row[5] or 0),
            conflicting_document_count=int(row[6] or 0),
            stale_link_count=int(row[7] or 0),
            missing_link_count=int(row[8] or 0),
            reason_codes=tuple(str(item) for item in raw_codes if str(item).strip()),
            checked_at=str(row[10]),
        )

    def upsert_entry(
        self,
        *,
        workspace_id: object,
        entry_kind: object,
        statement: object,
        origin_kind: object = "",
        origin_id: object = "",
        query: object = "",
        links: tuple[EvidenceLedgerLinkDraft, ...] | list[EvidenceLedgerLinkDraft] = (),
    ) -> EvidenceLedgerEntryRecord:
        workspace = _clean(workspace_id, limit=128)
        kind = _clean(entry_kind, limit=32)
        text = _clean(statement, limit=4000)
        normalized = _normalized(text)
        if not workspace or kind not in {"claim", "relation"} or not normalized:
            raise ValueError("Evidence Ledger requires workspace, claim/relation kind and statement.")
        if len(links) > 512:
            raise ValueError("Evidence Ledger supports at most 512 provenance links per entry.")

        now = _now_iso()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    row = connection.execute(
                        """
                        SELECT entry_id, workspace_id, entry_kind, statement,
                               normalized_statement, origin_kind, origin_id, query,
                               created_at, updated_at
                        FROM evidence_ledger_entries
                        WHERE workspace_id = ? AND entry_kind = ? AND normalized_statement = ?
                        """,
                        (workspace, kind, normalized),
                    ).fetchone()
                    if row is None:
                        entry_id = uuid4().hex
                        created_at = now
                        connection.execute(
                            """
                            INSERT INTO evidence_ledger_entries(
                                entry_id, workspace_id, entry_kind, statement,
                                normalized_statement, origin_kind, origin_id, query,
                                created_at, updated_at
                            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                entry_id,
                                workspace,
                                kind,
                                text,
                                normalized,
                                _clean(origin_kind, limit=64),
                                _clean(origin_id, limit=128),
                                _clean(query, limit=4000),
                                created_at,
                                now,
                            ),
                        )
                    else:
                        entry_id = str(row[0])
                        created_at = str(row[8])
                        connection.execute(
                            """
                            UPDATE evidence_ledger_entries
                            SET statement = ?, origin_kind = ?, origin_id = ?, query = ?, updated_at = ?
                            WHERE entry_id = ?
                            """,
                            (
                                text,
                                _clean(origin_kind, limit=64),
                                _clean(origin_id, limit=128),
                                _clean(query, limit=4000),
                                now,
                                entry_id,
                            ),
                        )
                        connection.execute(
                            "DELETE FROM evidence_ledger_links WHERE entry_id = ?",
                            (entry_id,),
                        )

                    for draft in links:
                        role = _clean(draft.role, limit=32)
                        support_kind = _clean(draft.support_kind, limit=32)
                        evidence_id = _clean(draft.evidence_id, limit=128)
                        note_id = _clean(draft.note_id, limit=128)
                        document_id = _clean(draft.document_id, limit=64)
                        if role not in {"supporting", "conflicting"}:
                            raise ValueError("Evidence Ledger link role must be supporting or conflicting.")
                        if support_kind not in {"claim", "relation"}:
                            raise ValueError("Evidence Ledger link support_kind must be claim or relation.")
                        if not evidence_id or not note_id or not document_id:
                            raise ValueError("Evidence Ledger links require evidence, note and document IDs.")
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO evidence_ledger_links(
                                link_id, entry_id, role, support_kind, claim_id,
                                relation_id, evidence_id, note_id, document_id,
                                confidence, captured_source_status, created_at
                            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                uuid4().hex,
                                entry_id,
                                role,
                                support_kind,
                                _clean(draft.claim_id, limit=128),
                                _clean(draft.relation_id, limit=128),
                                evidence_id,
                                note_id,
                                document_id,
                                _bounded_confidence(draft.confidence),
                                _clean(draft.captured_source_status, limit=64) or "legacy_unknown",
                                now,
                            ),
                        )
            return EvidenceLedgerEntryRecord(
                entry_id=entry_id,
                workspace_id=workspace,
                entry_kind=kind,
                statement=text,
                normalized_statement=normalized,
                origin_kind=_clean(origin_kind, limit=64),
                origin_id=_clean(origin_id, limit=128),
                query=_clean(query, limit=4000),
                created_at=created_at,
                updated_at=now,
            )
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc

    def list_entries(
        self,
        *,
        workspace_id: object,
        limit: int = DEFAULT_LEDGER_LIMIT,
    ) -> tuple[EvidenceLedgerEntryRecord, ...]:
        workspace = _clean(workspace_id, limit=128)
        if not workspace:
            return ()
        bounded_limit = max(1, min(MAX_LEDGER_LIMIT, int(limit)))
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT entry_id, workspace_id, entry_kind, statement,
                           normalized_statement, origin_kind, origin_id, query,
                           created_at, updated_at
                    FROM evidence_ledger_entries
                    WHERE workspace_id = ?
                    ORDER BY updated_at DESC, entry_id ASC
                    LIMIT ?
                    """,
                    (workspace, bounded_limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc
        return tuple(self._row_to_entry(row) for row in rows)

    def get_entry(self, entry_id: object) -> EvidenceLedgerEntryRecord | None:
        identifier = _clean(entry_id, limit=128)
        if not identifier:
            return None
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT entry_id, workspace_id, entry_kind, statement,
                           normalized_statement, origin_kind, origin_id, query,
                           created_at, updated_at
                    FROM evidence_ledger_entries WHERE entry_id = ?
                    """,
                    (identifier,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc
        return self._row_to_entry(row) if row is not None else None

    def links_for_entry(self, entry_id: object) -> tuple[EvidenceLedgerLinkRecord, ...]:
        identifier = _clean(entry_id, limit=128)
        if not identifier:
            return ()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT link_id, entry_id, role, support_kind, claim_id,
                           relation_id, evidence_id, note_id, document_id,
                           confidence, captured_source_status, created_at
                    FROM evidence_ledger_links
                    WHERE entry_id = ?
                    ORDER BY role DESC, confidence DESC, link_id ASC
                    """,
                    (identifier,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc
        return tuple(self._row_to_link(row) for row in rows)

    def latest_validation(self, entry_id: object) -> EvidenceLedgerValidationRecord | None:
        identifier = _clean(entry_id, limit=128)
        if not identifier:
            return None
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT validation_id, entry_id, status, usable_support_count,
                           usable_conflict_count, supporting_document_count,
                           conflicting_document_count, stale_link_count,
                           missing_link_count, reason_codes_json, checked_at
                    FROM evidence_ledger_validations
                    WHERE entry_id = ?
                    ORDER BY checked_at DESC, validation_id DESC
                    LIMIT 1
                    """,
                    (identifier,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc
        return self._row_to_validation(row) if row is not None else None

    def record_validation(
        self,
        *,
        entry_id: object,
        status: object,
        usable_support_count: int,
        usable_conflict_count: int,
        supporting_document_count: int,
        conflicting_document_count: int,
        stale_link_count: int,
        missing_link_count: int,
        reason_codes: tuple[str, ...] | list[str] = (),
    ) -> EvidenceLedgerValidationRecord:
        identifier = _clean(entry_id, limit=128)
        normalized_status = _clean(status, limit=32)
        if not identifier or normalized_status not in {
            "supported",
            "contested",
            "insufficient",
            "stale",
        }:
            raise ValueError("Evidence Ledger validation requires a valid entry and status.")
        codes = tuple(dict.fromkeys(_clean(item, limit=128) for item in reason_codes if _clean(item)))
        candidate = (
            normalized_status,
            max(0, int(usable_support_count)),
            max(0, int(usable_conflict_count)),
            max(0, int(supporting_document_count)),
            max(0, int(conflicting_document_count)),
            max(0, int(stale_link_count)),
            max(0, int(missing_link_count)),
            codes,
        )
        previous = self.latest_validation(identifier)
        if previous is not None:
            previous_signature = (
                previous.status,
                previous.usable_support_count,
                previous.usable_conflict_count,
                previous.supporting_document_count,
                previous.conflicting_document_count,
                previous.stale_link_count,
                previous.missing_link_count,
                previous.reason_codes,
            )
            if previous_signature == candidate:
                return previous

        now = _now_iso()
        record = EvidenceLedgerValidationRecord(
            validation_id=uuid4().hex,
            entry_id=identifier,
            status=candidate[0],
            usable_support_count=candidate[1],
            usable_conflict_count=candidate[2],
            supporting_document_count=candidate[3],
            conflicting_document_count=candidate[4],
            stale_link_count=candidate[5],
            missing_link_count=candidate[6],
            reason_codes=candidate[7],
            checked_at=now,
        )
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO evidence_ledger_validations(
                            validation_id, entry_id, status, usable_support_count,
                            usable_conflict_count, supporting_document_count,
                            conflicting_document_count, stale_link_count,
                            missing_link_count, reason_codes_json, checked_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.validation_id,
                            record.entry_id,
                            record.status,
                            record.usable_support_count,
                            record.usable_conflict_count,
                            record.supporting_document_count,
                            record.conflicting_document_count,
                            record.stale_link_count,
                            record.missing_link_count,
                            json.dumps(record.reason_codes, ensure_ascii=False),
                            record.checked_at,
                        ),
                    )
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc
        return record

    def delete_workspace(self, workspace_id: object) -> int:
        workspace = _clean(workspace_id, limit=128)
        if not workspace:
            return 0
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        "DELETE FROM evidence_ledger_entries WHERE workspace_id = ?",
                        (workspace,),
                    )
                    return max(0, int(cursor.rowcount or 0))
        except sqlite3.Error as exc:
            raise RuntimeError("Evidence Ledger storage is unavailable.") from exc


__all__ = [
    "EvidenceLedgerEntryRecord",
    "EvidenceLedgerLinkDraft",
    "EvidenceLedgerLinkRecord",
    "EvidenceLedgerStore",
    "EvidenceLedgerValidationRecord",
]
