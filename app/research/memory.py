"""SQLite-backed structured research memory for Research Workspaces.

Stage 17 keeps structured memory in a separate database from Research Notes.
Research Notes remain the source of truth; claims, evidence, entities and
relations are derived, replaceable indexes that always retain stable links back
to the originating Workspace and Note.
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

DEFAULT_RESEARCH_MEMORY_FILENAME = "research_memory.sqlite3"
RESEARCH_MEMORY_SCHEMA_VERSION = 1
DEFAULT_MEMORY_LIMIT = 100
MAX_MEMORY_LIMIT = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_storage_path() -> Path:
    return writable_config_dir() / DEFAULT_RESEARCH_MEMORY_FILENAME


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
class ResearchMemoryClaimDraft:
    text: str
    claim_type: str = "other"
    confidence: float = 0.0
    evidence_excerpt: str = ""


@dataclass(frozen=True, slots=True)
class ResearchMemoryEntityDraft:
    canonical_name: str
    entity_type: str = "concept"
    aliases: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class ResearchMemoryRelationDraft:
    subject: str
    predicate: str
    object: str
    claim_index: int | None = None
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ResearchMemoryExtractionDraft:
    claims: tuple[ResearchMemoryClaimDraft, ...] = ()
    entities: tuple[ResearchMemoryEntityDraft, ...] = ()
    relations: tuple[ResearchMemoryRelationDraft, ...] = ()
    extractor_version: str = ""
    prompt_id: str = ""


@dataclass(frozen=True, slots=True)
class ResearchMemoryExtractionRecord:
    extraction_id: str
    workspace_id: str
    note_id: str
    extractor_version: str
    prompt_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ResearchMemoryClaim:
    claim_id: str
    extraction_id: str
    workspace_id: str
    note_id: str
    claim_type: str
    text: str
    normalized_text: str
    confidence: float
    created_at: str


@dataclass(frozen=True, slots=True)
class ResearchMemoryEvidence:
    evidence_id: str
    claim_id: str
    workspace_id: str
    note_id: str
    excerpt: str
    start_offset: int
    end_offset: int
    created_at: str


@dataclass(frozen=True, slots=True)
class ResearchMemoryEntity:
    entity_id: str
    workspace_id: str
    canonical_name: str
    normalized_name: str
    entity_type: str
    aliases: tuple[str, ...]
    description: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ResearchMemoryRelation:
    relation_id: str
    extraction_id: str
    workspace_id: str
    note_id: str
    source_entity_id: str
    predicate: str
    target_entity_id: str
    claim_id: str
    confidence: float
    created_at: str


@dataclass(frozen=True, slots=True)
class ResearchMemorySnapshot:
    extractions: tuple[ResearchMemoryExtractionRecord, ...] = ()
    claims: tuple[ResearchMemoryClaim, ...] = ()
    evidence: tuple[ResearchMemoryEvidence, ...] = ()
    entities: tuple[ResearchMemoryEntity, ...] = ()
    relations: tuple[ResearchMemoryRelation, ...] = ()


class ResearchMemoryStore:
    """Persist replaceable structured memory derived from Research Notes."""

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

            CREATE TABLE IF NOT EXISTS research_memory_extractions (
                extraction_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                extractor_version TEXT NOT NULL DEFAULT '',
                prompt_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, note_id)
            );

            CREATE TABLE IF NOT EXISTS research_memory_claims (
                claim_id TEXT PRIMARY KEY,
                extraction_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(extraction_id)
                    REFERENCES research_memory_extractions(extraction_id)
                    ON DELETE CASCADE,
                UNIQUE(workspace_id, note_id, claim_type, normalized_text)
            );

            CREATE TABLE IF NOT EXISTS research_memory_evidence (
                evidence_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                start_offset INTEGER NOT NULL DEFAULT -1,
                end_offset INTEGER NOT NULL DEFAULT -1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(claim_id)
                    REFERENCES research_memory_claims(claim_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS research_memory_entities (
                entity_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, normalized_name, entity_type)
            );

            CREATE TABLE IF NOT EXISTS research_memory_relations (
                relation_id TEXT PRIMARY KEY,
                extraction_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                source_entity_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                target_entity_id TEXT NOT NULL,
                claim_id TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(extraction_id)
                    REFERENCES research_memory_extractions(extraction_id)
                    ON DELETE CASCADE,
                FOREIGN KEY(source_entity_id)
                    REFERENCES research_memory_entities(entity_id),
                FOREIGN KEY(target_entity_id)
                    REFERENCES research_memory_entities(entity_id),
                UNIQUE(
                    extraction_id,
                    source_entity_id,
                    predicate,
                    target_entity_id,
                    claim_id
                )
            );

            CREATE INDEX IF NOT EXISTS idx_memory_extractions_workspace
                ON research_memory_extractions(workspace_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_claims_workspace
                ON research_memory_claims(workspace_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_claims_note
                ON research_memory_claims(note_id);
            CREATE INDEX IF NOT EXISTS idx_memory_evidence_workspace
                ON research_memory_evidence(workspace_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_entities_workspace
                ON research_memory_entities(workspace_id, normalized_name);
            CREATE INDEX IF NOT EXISTS idx_memory_relations_workspace
                ON research_memory_relations(workspace_id, created_at DESC);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(RESEARCH_MEMORY_SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
        except (OSError, sqlite3.Error):
            # Derived memory must never prevent the application from starting.
            return

    @staticmethod
    def _row_to_extraction(row: tuple[object, ...]) -> ResearchMemoryExtractionRecord:
        return ResearchMemoryExtractionRecord(
            extraction_id=str(row[0]),
            workspace_id=str(row[1]),
            note_id=str(row[2]),
            extractor_version=str(row[3] or ""),
            prompt_id=str(row[4] or ""),
            created_at=str(row[5] or ""),
            updated_at=str(row[6] or ""),
        )

    @staticmethod
    def _row_to_claim(row: tuple[object, ...]) -> ResearchMemoryClaim:
        return ResearchMemoryClaim(
            claim_id=str(row[0]),
            extraction_id=str(row[1]),
            workspace_id=str(row[2]),
            note_id=str(row[3]),
            claim_type=str(row[4]),
            text=str(row[5]),
            normalized_text=str(row[6]),
            confidence=float(row[7] or 0.0),
            created_at=str(row[8] or ""),
        )

    @staticmethod
    def _row_to_evidence(row: tuple[object, ...]) -> ResearchMemoryEvidence:
        return ResearchMemoryEvidence(
            evidence_id=str(row[0]),
            claim_id=str(row[1]),
            workspace_id=str(row[2]),
            note_id=str(row[3]),
            excerpt=str(row[4]),
            start_offset=int(row[5]),
            end_offset=int(row[6]),
            created_at=str(row[7] or ""),
        )

    @staticmethod
    def _row_to_entity(row: tuple[object, ...]) -> ResearchMemoryEntity:
        try:
            raw_aliases = json.loads(str(row[5] or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            raw_aliases = []
        aliases = tuple(str(item) for item in raw_aliases if str(item).strip())
        return ResearchMemoryEntity(
            entity_id=str(row[0]),
            workspace_id=str(row[1]),
            canonical_name=str(row[2]),
            normalized_name=str(row[3]),
            entity_type=str(row[4]),
            aliases=aliases,
            description=str(row[6] or ""),
            created_at=str(row[7] or ""),
            updated_at=str(row[8] or ""),
        )

    @staticmethod
    def _row_to_relation(row: tuple[object, ...]) -> ResearchMemoryRelation:
        return ResearchMemoryRelation(
            relation_id=str(row[0]),
            extraction_id=str(row[1]),
            workspace_id=str(row[2]),
            note_id=str(row[3]),
            source_entity_id=str(row[4]),
            predicate=str(row[5]),
            target_entity_id=str(row[6]),
            claim_id=str(row[7] or ""),
            confidence=float(row[8] or 0.0),
            created_at=str(row[9] or ""),
        )

    @staticmethod
    def _find_excerpt(source_text: str, excerpt: str) -> tuple[int, int]:
        source = str(source_text or "")
        candidate = _clean(excerpt, limit=4000)
        if not source or not candidate:
            return (-1, -1)
        offset = source.find(candidate)
        if offset < 0:
            return (-1, -1)
        return (offset, offset + len(candidate))

    @staticmethod
    def _upsert_entity(
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        draft: ResearchMemoryEntityDraft,
        now: str,
    ) -> tuple[str, str]:
        canonical_name = _clean(draft.canonical_name, limit=500)
        normalized_name = _normalized(canonical_name)
        entity_type = _clean(draft.entity_type or "concept", limit=128) or "concept"
        if not normalized_name:
            raise ValueError("Research-memory entity requires a canonical name.")
        aliases: list[str] = []
        seen: set[str] = set()
        for value in draft.aliases:
            alias = _clean(value, limit=500)
            folded = _normalized(alias)
            if not alias or not folded or folded in seen or folded == normalized_name:
                continue
            aliases.append(alias)
            seen.add(folded)
            if len(aliases) >= 20:
                break
        description = _clean(draft.description, limit=2000)
        row = connection.execute(
            """
            SELECT entity_id, aliases_json, description
            FROM research_memory_entities
            WHERE workspace_id = ? AND normalized_name = ? AND entity_type = ?
            """,
            (workspace_id, normalized_name, entity_type),
        ).fetchone()
        if row is None:
            entity_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO research_memory_entities(
                    entity_id, workspace_id, canonical_name, normalized_name,
                    entity_type, aliases_json, description, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    workspace_id,
                    canonical_name,
                    normalized_name,
                    entity_type,
                    json.dumps(aliases, ensure_ascii=False),
                    description,
                    now,
                    now,
                ),
            )
            return (normalized_name, entity_id)

        entity_id = str(row[0])
        try:
            previous_aliases = [
                str(item) for item in json.loads(str(row[1] or "[]")) if str(item).strip()
            ]
        except (json.JSONDecodeError, TypeError, ValueError):
            previous_aliases = []
        merged: list[str] = []
        merged_seen: set[str] = set()
        for alias in [*previous_aliases, *aliases]:
            folded = _normalized(alias)
            if not folded or folded in merged_seen or folded == normalized_name:
                continue
            merged.append(alias)
            merged_seen.add(folded)
            if len(merged) >= 20:
                break
        merged_description = description or str(row[2] or "")
        connection.execute(
            """
            UPDATE research_memory_entities
            SET canonical_name = ?, aliases_json = ?, description = ?, updated_at = ?
            WHERE entity_id = ?
            """,
            (
                canonical_name,
                json.dumps(merged, ensure_ascii=False),
                merged_description,
                now,
                entity_id,
            ),
        )
        return (normalized_name, entity_id)

    def replace_note_memory(
        self,
        *,
        workspace_id: object,
        note_id: object,
        source_text: object,
        extraction: ResearchMemoryExtractionDraft,
    ) -> ResearchMemoryExtractionRecord:
        workspace = _clean(workspace_id, limit=128)
        note = _clean(note_id, limit=128)
        if not workspace or not note:
            raise ValueError("Structured research memory requires workspace_id and note_id.")
        if len(extraction.claims) > 24:
            raise ValueError("Structured research memory supports at most 24 claims per note.")
        if len(extraction.entities) > 40:
            raise ValueError("Structured research memory supports at most 40 entities per note.")
        if len(extraction.relations) > 60:
            raise ValueError("Structured research memory supports at most 60 relations per note.")

        now = _now_iso()
        source = str(source_text or "")
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    existing = connection.execute(
                        """
                        SELECT extraction_id, created_at
                        FROM research_memory_extractions
                        WHERE workspace_id = ? AND note_id = ?
                        """,
                        (workspace, note),
                    ).fetchone()
                    if existing is None:
                        extraction_id = uuid4().hex
                        created_at = now
                        connection.execute(
                            """
                            INSERT INTO research_memory_extractions(
                                extraction_id, workspace_id, note_id,
                                extractor_version, prompt_id, created_at, updated_at
                            ) VALUES(?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                extraction_id,
                                workspace,
                                note,
                                _clean(extraction.extractor_version, limit=128),
                                _clean(extraction.prompt_id, limit=256),
                                created_at,
                                now,
                            ),
                        )
                    else:
                        extraction_id = str(existing[0])
                        created_at = str(existing[1] or now)
                        connection.execute(
                            "DELETE FROM research_memory_relations WHERE extraction_id = ?",
                            (extraction_id,),
                        )
                        connection.execute(
                            "DELETE FROM research_memory_claims WHERE extraction_id = ?",
                            (extraction_id,),
                        )
                        connection.execute(
                            """
                            UPDATE research_memory_extractions
                            SET extractor_version = ?, prompt_id = ?, updated_at = ?
                            WHERE extraction_id = ?
                            """,
                            (
                                _clean(extraction.extractor_version, limit=128),
                                _clean(extraction.prompt_id, limit=256),
                                now,
                                extraction_id,
                            ),
                        )

                    claim_ids: list[str] = []
                    for draft in extraction.claims:
                        text = _clean(draft.text, limit=5000)
                        normalized_text = _normalized(text)
                        if not normalized_text:
                            claim_ids.append("")
                            continue
                        claim_id = uuid4().hex
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO research_memory_claims(
                                claim_id, extraction_id, workspace_id, note_id,
                                claim_type, text, normalized_text, confidence, created_at
                            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                claim_id,
                                extraction_id,
                                workspace,
                                note,
                                _clean(draft.claim_type or "other", limit=128) or "other",
                                text,
                                normalized_text,
                                _bounded_confidence(draft.confidence),
                                now,
                            ),
                        )
                        persisted = connection.execute(
                            """
                            SELECT claim_id FROM research_memory_claims
                            WHERE workspace_id = ? AND note_id = ?
                              AND claim_type = ? AND normalized_text = ?
                            """,
                            (
                                workspace,
                                note,
                                _clean(draft.claim_type or "other", limit=128) or "other",
                                normalized_text,
                            ),
                        ).fetchone()
                        persisted_claim_id = str(persisted[0]) if persisted else ""
                        claim_ids.append(persisted_claim_id)
                        excerpt = _clean(draft.evidence_excerpt, limit=4000)
                        if persisted_claim_id and excerpt:
                            start, end = self._find_excerpt(source, excerpt)
                            connection.execute(
                                """
                                INSERT INTO research_memory_evidence(
                                    evidence_id, claim_id, workspace_id, note_id,
                                    excerpt, start_offset, end_offset, created_at
                                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    uuid4().hex,
                                    persisted_claim_id,
                                    workspace,
                                    note,
                                    excerpt,
                                    start,
                                    end,
                                    now,
                                ),
                            )

                    entity_ids: dict[str, str] = {}
                    alias_ids: dict[str, str] = {}
                    for draft in extraction.entities:
                        normalized_name, entity_id = self._upsert_entity(
                            connection,
                            workspace_id=workspace,
                            draft=draft,
                            now=now,
                        )
                        entity_ids[normalized_name] = entity_id
                        for alias in draft.aliases:
                            folded = _normalized(alias)
                            if folded:
                                alias_ids[folded] = entity_id

                    for draft in extraction.relations:
                        source_id = entity_ids.get(_normalized(draft.subject)) or alias_ids.get(
                            _normalized(draft.subject)
                        )
                        target_id = entity_ids.get(_normalized(draft.object)) or alias_ids.get(
                            _normalized(draft.object)
                        )
                        predicate = _clean(draft.predicate, limit=256)
                        if not source_id or not target_id or not predicate:
                            continue
                        claim_id = ""
                        if draft.claim_index is not None:
                            try:
                                index = int(draft.claim_index)
                            except (TypeError, ValueError):
                                index = -1
                            if 0 <= index < len(claim_ids):
                                claim_id = claim_ids[index]
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO research_memory_relations(
                                relation_id, extraction_id, workspace_id, note_id,
                                source_entity_id, predicate, target_entity_id,
                                claim_id, confidence, created_at
                            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                uuid4().hex,
                                extraction_id,
                                workspace,
                                note,
                                source_id,
                                predicate,
                                target_id,
                                claim_id,
                                _bounded_confidence(draft.confidence),
                                now,
                            ),
                        )

                    row = connection.execute(
                        """
                        SELECT extraction_id, workspace_id, note_id, extractor_version,
                               prompt_id, created_at, updated_at
                        FROM research_memory_extractions
                        WHERE extraction_id = ?
                        """,
                        (extraction_id,),
                    ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeError("Unable to persist structured research memory.") from exc
        if row is None:
            raise RuntimeError("Structured research memory extraction was not persisted.")
        return self._row_to_extraction(row)

    def delete_note_memory(self, *, workspace_id: object, note_id: object) -> bool:
        workspace = _clean(workspace_id, limit=128)
        note = _clean(note_id, limit=128)
        if not workspace or not note:
            return False
        try:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)
                    cursor = connection.execute(
                        "DELETE FROM research_memory_extractions WHERE workspace_id = ? AND note_id = ?",
                        (workspace, note),
                    )
                    return cursor.rowcount > 0
        except (OSError, sqlite3.Error):
            return False

    @staticmethod
    def _bounded_limit(limit: object) -> int:
        try:
            return max(1, min(MAX_MEMORY_LIMIT, int(limit)))
        except (TypeError, ValueError):
            return DEFAULT_MEMORY_LIMIT

    def snapshot(
        self,
        *,
        workspace_id: object,
        limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> ResearchMemorySnapshot:
        workspace = _clean(workspace_id, limit=128)
        if not workspace:
            return ResearchMemorySnapshot()
        bounded = self._bounded_limit(limit)
        try:
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                extractions = connection.execute(
                    """
                    SELECT extraction_id, workspace_id, note_id, extractor_version,
                           prompt_id, created_at, updated_at
                    FROM research_memory_extractions
                    WHERE workspace_id = ? ORDER BY updated_at DESC LIMIT ?
                    """,
                    (workspace, bounded),
                ).fetchall()
                claims = connection.execute(
                    """
                    SELECT claim_id, extraction_id, workspace_id, note_id,
                           claim_type, text, normalized_text, confidence, created_at
                    FROM research_memory_claims
                    WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (workspace, bounded),
                ).fetchall()
                evidence = connection.execute(
                    """
                    SELECT evidence_id, claim_id, workspace_id, note_id,
                           excerpt, start_offset, end_offset, created_at
                    FROM research_memory_evidence
                    WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (workspace, bounded),
                ).fetchall()
                entities = connection.execute(
                    """
                    SELECT entity_id, workspace_id, canonical_name, normalized_name,
                           entity_type, aliases_json, description, created_at, updated_at
                    FROM research_memory_entities
                    WHERE workspace_id = ? ORDER BY updated_at DESC LIMIT ?
                    """,
                    (workspace, bounded),
                ).fetchall()
                relations = connection.execute(
                    """
                    SELECT relation_id, extraction_id, workspace_id, note_id,
                           source_entity_id, predicate, target_entity_id,
                           claim_id, confidence, created_at
                    FROM research_memory_relations
                    WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (workspace, bounded),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return ResearchMemorySnapshot()
        return ResearchMemorySnapshot(
            extractions=tuple(self._row_to_extraction(row) for row in extractions),
            claims=tuple(self._row_to_claim(row) for row in claims),
            evidence=tuple(self._row_to_evidence(row) for row in evidence),
            entities=tuple(self._row_to_entity(row) for row in entities),
            relations=tuple(self._row_to_relation(row) for row in relations),
        )


__all__ = [
    "ResearchMemoryClaim",
    "ResearchMemoryClaimDraft",
    "ResearchMemoryEntity",
    "ResearchMemoryEntityDraft",
    "ResearchMemoryEvidence",
    "ResearchMemoryExtractionDraft",
    "ResearchMemoryExtractionRecord",
    "ResearchMemoryRelation",
    "ResearchMemoryRelationDraft",
    "ResearchMemorySnapshot",
    "ResearchMemoryStore",
]
