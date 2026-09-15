from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock

from backend.knowledge.domain import (
    KnowledgeRelationSuggestion,
    KnowledgeRelationSuggestionStatus,
)


class SqliteKnowledgeRelationSuggestionRepository:
    """Durable review queue for AI-proposed knowledge relations.

    Suggestions live outside the canonical ``knowledge_relations`` table until
    a user explicitly accepts them. This keeps model output auditable without
    allowing generation to mutate the knowledge graph directly.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path).expanduser().resolve()
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.storage_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_relation_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    focus_item_id TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    target_item_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL,
                    evidence_item_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    accepted_relation_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(focus_item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                    FOREIGN KEY(source_item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                    FOREIGN KEY(target_item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                    FOREIGN KEY(accepted_relation_id) REFERENCES knowledge_relations(relation_id) ON DELETE SET NULL,
                    CHECK(source_item_id <> target_item_id),
                    CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    CHECK(status IN ('pending', 'accepted', 'rejected'))
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_relation_suggestions_focus_status
                    ON knowledge_relation_suggestions(focus_item_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_relation_suggestions_pair
                    ON knowledge_relation_suggestions(source_item_id, target_item_id, relation_type, status);
                """
            )

    @staticmethod
    def _decode_list(value: str) -> list[str]:
        try:
            loaded = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, list):
            return []
        return [str(item) for item in loaded if str(item).strip()]

    @staticmethod
    def _decode_dict(value: str) -> dict[str, object]:
        try:
            loaded = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @classmethod
    def _suggestion(cls, row: sqlite3.Row) -> KnowledgeRelationSuggestion:
        return KnowledgeRelationSuggestion(
            suggestion_id=row["suggestion_id"],
            focus_item_id=row["focus_item_id"],
            source_item_id=row["source_item_id"],
            target_item_id=row["target_item_id"],
            relation_type=row["relation_type"],
            label=row["label"],
            rationale=row["rationale"],
            confidence=row["confidence"],
            evidence_item_ids=cls._decode_list(row["evidence_item_ids_json"]),
            status=KnowledgeRelationSuggestionStatus(row["status"]),
            accepted_relation_id=row["accepted_relation_id"],
            metadata=cls._decode_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(self, suggestion: KnowledgeRelationSuggestion) -> KnowledgeRelationSuggestion:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_relation_suggestions(
                        suggestion_id, focus_item_id, source_item_id, target_item_id,
                        relation_type, label, rationale, confidence,
                        evidence_item_ids_json, status, accepted_relation_id,
                        metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(suggestion_id) DO UPDATE SET
                        focus_item_id=excluded.focus_item_id,
                        source_item_id=excluded.source_item_id,
                        target_item_id=excluded.target_item_id,
                        relation_type=excluded.relation_type,
                        label=excluded.label,
                        rationale=excluded.rationale,
                        confidence=excluded.confidence,
                        evidence_item_ids_json=excluded.evidence_item_ids_json,
                        status=excluded.status,
                        accepted_relation_id=excluded.accepted_relation_id,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        suggestion.suggestion_id,
                        suggestion.focus_item_id,
                        suggestion.source_item_id,
                        suggestion.target_item_id,
                        suggestion.relation_type,
                        suggestion.label,
                        suggestion.rationale,
                        suggestion.confidence,
                        json.dumps(suggestion.evidence_item_ids, ensure_ascii=False),
                        suggestion.status.value,
                        suggestion.accepted_relation_id,
                        json.dumps(suggestion.metadata, ensure_ascii=False),
                        suggestion.created_at.isoformat(),
                        suggestion.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"knowledge relation suggestion violates repository constraints: {exc}"
                ) from exc
        stored = self.get(suggestion.suggestion_id)
        if stored is None:
            raise RuntimeError("knowledge relation suggestion was not persisted")
        return stored

    def get(self, suggestion_id: str) -> KnowledgeRelationSuggestion | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_relation_suggestions WHERE suggestion_id = ?",
                (suggestion_id,),
            ).fetchone()
        return self._suggestion(row) if row is not None else None

    def list(
        self,
        *,
        focus_item_id: str | None = None,
        status: KnowledgeRelationSuggestionStatus | None = None,
    ) -> list[KnowledgeRelationSuggestion]:
        where: list[str] = []
        params: list[str] = []
        if focus_item_id:
            where.append("focus_item_id = ?")
            params.append(focus_item_id)
        if status is not None:
            where.append("status = ?")
            params.append(status.value)
        sql = "SELECT * FROM knowledge_relation_suggestions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, suggestion_id ASC"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._suggestion(row) for row in rows]


__all__ = ["SqliteKnowledgeRelationSuggestionRepository"]
