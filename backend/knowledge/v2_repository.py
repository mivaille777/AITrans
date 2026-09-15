from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Any

from backend.knowledge.domain import (
    KnowledgeItem,
    KnowledgeItemType,
    KnowledgeRelation,
    KnowledgeRelationOrigin,
    utc_now,
)
from backend.knowledge.repository import SqliteKnowledgeRepository

_V2_ITEM_TYPES = {
    KnowledgeItemType.CONCEPT,
    KnowledgeItemType.EVIDENCE,
    KnowledgeItemType.INSIGHT,
    KnowledgeItemType.QUESTION,
}
_V2_METADATA_KEY = "knowledge_v2"


class KnowledgeV2Repository:
    """Compatibility adapter for the legacy Knowledge 2.0 API.

    Cards and relations are persisted in the canonical KnowledgeItem /
    KnowledgeRelation tables. Legacy ``*_v2`` card/relation tables are treated
    only as migration sources when they already exist. Agent events remain in
    their legacy audit table until the event model is unified separately.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path).expanduser().resolve()
        self._lock = RLock()
        self._canonical = SqliteKnowledgeRepository(self.storage_path)
        self._initialize_compatibility()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.storage_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _initialize_compatibility(self) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_agent_events_v2 (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    input_json TEXT DEFAULT '{}',
                    output_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            legacy_cards = self._legacy_rows(conn, "knowledge_cards_v2")
            legacy_relations = self._legacy_rows(conn, "knowledge_relations_v2")

        self._migrate_legacy_cards(legacy_cards)
        self._migrate_legacy_relations(legacy_relations)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    @classmethod
    def _legacy_rows(cls, conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
        if not cls._table_exists(conn, table_name):
            return []
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        return [dict(row) for row in rows]

    def _migrate_legacy_cards(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            card_id = str(row.get("id") or "").strip()
            if not card_id or self._canonical.get_item(card_id) is not None:
                continue
            try:
                item_type = self._v2_item_type(row.get("type"))
                confidence = self._confidence(row.get("confidence", 0.0))
                content = self._loads_dict(row.get("content_json"))
                item = KnowledgeItem(
                    item_id=card_id,
                    item_type=item_type,
                    title=str(row.get("title") or "").strip() or "Untitled knowledge card",
                    summary=str(row.get("summary") or ""),
                    metadata={
                        "confidence": confidence,
                        "content": content,
                        "provenance": {
                            "created_by": "system",
                            "operation": "knowledge_v2_legacy_migration",
                        },
                        _V2_METADATA_KEY: {"legacy_migrated": True},
                    },
                    created_at=row.get("created_at") or utc_now(),
                    updated_at=row.get("updated_at") or row.get("created_at") or utc_now(),
                )
                self._canonical.save_item(item)
            except (TypeError, ValueError):
                continue

    def _migrate_legacy_relations(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            relation_id = str(row.get("id") or "").strip()
            source_id = str(row.get("source_card_id") or "").strip()
            target_id = str(row.get("target_card_id") or "").strip()
            if (
                not relation_id
                or not source_id
                or not target_id
                or source_id == target_id
                or self._canonical.get_relation(relation_id) is not None
                or self.get_card(source_id) is None
                or self.get_card(target_id) is None
            ):
                continue
            try:
                created_by = str(row.get("created_by") or "agent")
                relation = KnowledgeRelation(
                    relation_id=relation_id,
                    source_item_id=source_id,
                    target_item_id=target_id,
                    relation_type=str(row.get("relation_type") or "related_to"),
                    origin=self._origin(created_by),
                    confidence=self._confidence(row.get("confidence", 0.0)),
                    metadata={
                        "created_by": created_by,
                        _V2_METADATA_KEY: {"legacy_migrated": True},
                    },
                )
                self._canonical.save_relation(relation)
            except (TypeError, ValueError):
                continue

    def create_card(self, card: dict[str, Any]) -> dict[str, Any]:
        card_id = str(card.get("id") or "").strip()
        if not card_id:
            raise ValueError("knowledge v2 card id must not be empty")
        if self._canonical.get_item(card_id) is not None:
            raise ValueError(f"knowledge v2 card already exists: {card_id}")

        content = dict(card.get("content") or {})
        confidence = self._confidence(card.get("confidence", 0.0))
        item = KnowledgeItem(
            item_id=card_id,
            item_type=self._v2_item_type(card.get("type")),
            title=str(card.get("title") or "").strip(),
            summary=str(card.get("summary") or ""),
            metadata={
                "confidence": confidence,
                "content": content,
                "provenance": {
                    "created_by": "system",
                    "operation": "knowledge_v2_compat_create",
                },
                _V2_METADATA_KEY: {"compat": True},
            },
            created_at=card.get("created_at") or utc_now(),
            updated_at=card.get("updated_at") or card.get("created_at") or utc_now(),
        )
        stored = self._canonical.save_item(item)
        return self._card(stored)

    def list_cards(self) -> list[dict[str, Any]]:
        cards = [
            self._card(item)
            for item in self._canonical.list_items()
            if item.item_type in _V2_ITEM_TYPES
        ]
        return sorted(cards, key=lambda card: str(card["created_at"]), reverse=True)

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        item = self._canonical.get_item(card_id)
        if item is None or item.item_type not in _V2_ITEM_TYPES:
            return None
        return self._card(item)

    def create_relation(self, relation: dict[str, Any]) -> dict[str, Any]:
        relation_id = str(relation.get("id") or "").strip()
        source_id = str(relation.get("source_card_id") or "").strip()
        target_id = str(relation.get("target_card_id") or "").strip()
        if not relation_id:
            raise ValueError("knowledge v2 relation id must not be empty")
        if source_id == target_id:
            raise ValueError("knowledge v2 relation cannot target the same card")
        if self.get_card(source_id) is None:
            raise ValueError("source knowledge v2 card does not exist")
        if self.get_card(target_id) is None:
            raise ValueError("target knowledge v2 card does not exist")
        if self._canonical.get_relation(relation_id) is not None:
            raise ValueError(f"knowledge v2 relation already exists: {relation_id}")

        created_by = str(relation.get("created_by") or "agent")
        stored = self._canonical.save_relation(
            KnowledgeRelation(
                relation_id=relation_id,
                source_item_id=source_id,
                target_item_id=target_id,
                relation_type=str(relation.get("relation_type") or "related_to"),
                origin=self._origin(created_by),
                confidence=self._confidence(relation.get("confidence", 0.0)),
                metadata={
                    "created_by": created_by,
                    "evidence_ids": list(relation.get("evidence_ids") or []),
                    _V2_METADATA_KEY: {"compat": True},
                },
            )
        )
        return self._relation(stored)

    def get_graph(self) -> dict[str, list[Any]]:
        return {"nodes": self.list_cards(), "edges": self.list_relations()}

    def list_relations(self) -> list[dict[str, Any]]:
        card_ids = {str(card["id"]) for card in self.list_cards()}
        return [
            self._relation(relation)
            for relation in self._canonical.list_relations()
            if relation.source_item_id in card_ids and relation.target_item_id in card_ids
        ]

    def record_agent_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO knowledge_agent_events_v2(
                    id, agent_name, action, target_id, input_json, output_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["agent_name"],
                    event["action"],
                    event["target_id"],
                    self.dumps(event.get("input", {})),
                    self.dumps(event.get("output", {})),
                    event["created_at"],
                ),
            )
        return event

    def list_agent_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_agent_events_v2 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _card(item: KnowledgeItem) -> dict[str, Any]:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        return {
            "id": item.item_id,
            "type": item.item_type.value,
            "title": item.title,
            "summary": item.summary,
            "content": dict(metadata.get("content") or {}),
            "confidence": KnowledgeV2Repository._confidence(metadata.get("confidence", 0.0)),
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def _relation(relation: KnowledgeRelation) -> dict[str, Any]:
        metadata = relation.metadata if isinstance(relation.metadata, dict) else {}
        created_by = str(metadata.get("created_by") or ("agent" if relation.origin is KnowledgeRelationOrigin.AI else "user"))
        return {
            "id": relation.relation_id,
            "source_card_id": relation.source_item_id,
            "target_card_id": relation.target_item_id,
            "relation_type": relation.relation_type,
            "confidence": relation.confidence if relation.confidence is not None else 0.0,
            "created_by": created_by,
        }

    @staticmethod
    def _v2_item_type(value: Any) -> KnowledgeItemType:
        item_type = KnowledgeItemType(str(value or "").strip().casefold())
        if item_type not in _V2_ITEM_TYPES:
            raise ValueError(f"unsupported knowledge v2 card type: {item_type.value}")
        return item_type

    @staticmethod
    def _origin(created_by: str) -> KnowledgeRelationOrigin:
        return KnowledgeRelationOrigin.AI if created_by.strip().casefold() == "agent" else KnowledgeRelationOrigin.MANUAL

    @staticmethod
    def _confidence(value: Any) -> float:
        confidence = float(value or 0.0)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("knowledge v2 confidence must be between 0 and 1")
        return confidence

    @staticmethod
    def _loads_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if not value:
            return {}
        loaded = json.loads(str(value))
        return dict(loaded) if isinstance(loaded, dict) else {}

    @staticmethod
    def dumps(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
