from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Protocol

from backend.knowledge.domain import (
    KnowledgeCollection,
    KnowledgeItem,
    KnowledgeItemType,
    KnowledgeRelation,
    KnowledgeRelationOrigin,
    KnowledgeTag,
)

SCHEMA_VERSION = 1


class KnowledgeRepository(Protocol):
    def save_item(self, item: KnowledgeItem) -> KnowledgeItem: ...
    def get_item(self, item_id: str) -> KnowledgeItem | None: ...
    def find_item_by_resource_document_id(self, document_id: str) -> KnowledgeItem | None: ...
    def list_items(
        self,
        *,
        item_type: KnowledgeItemType | None = None,
        collection_id: str | None = None,
        tag_id: str | None = None,
    ) -> list[KnowledgeItem]: ...
    def delete_item(self, item_id: str) -> bool: ...
    def save_relation(self, relation: KnowledgeRelation) -> KnowledgeRelation: ...
    def get_relation(self, relation_id: str) -> KnowledgeRelation | None: ...
    def list_relations(self, *, item_id: str | None = None) -> list[KnowledgeRelation]: ...
    def delete_relation(self, relation_id: str) -> bool: ...
    def save_collection(self, collection: KnowledgeCollection) -> KnowledgeCollection: ...
    def get_collection(self, collection_id: str) -> KnowledgeCollection | None: ...
    def list_collections(self) -> list[KnowledgeCollection]: ...
    def delete_collection(self, collection_id: str) -> bool: ...
    def add_item_to_collection(self, item_id: str, collection_id: str) -> None: ...
    def remove_item_from_collection(self, item_id: str, collection_id: str) -> bool: ...
    def save_tag(self, tag: KnowledgeTag) -> KnowledgeTag: ...
    def get_tag(self, tag_id: str) -> KnowledgeTag | None: ...
    def list_tags(self) -> list[KnowledgeTag]: ...
    def delete_tag(self, tag_id: str) -> bool: ...
    def add_tag_to_item(self, item_id: str, tag_id: str) -> None: ...
    def remove_tag_from_item(self, item_id: str, tag_id: str) -> bool: ...


def _json_dump(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str) -> dict[str, object]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


class SqliteKnowledgeRepository:
    """Local-first persistence for user-owned knowledge semantics.

    This database intentionally does not store embeddings or parsed chunks.
    RAG assets remain owned by the existing index/vector-store layer, while
    this repository owns durable cards, relations, collections and tags.
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

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_items (
                item_id TEXT PRIMARY KEY,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                resource_document_id TEXT UNIQUE,
                source_uri TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_items_type_updated
                ON knowledge_items(item_type, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_items_updated
                ON knowledge_items(updated_at DESC);

            CREATE TABLE IF NOT EXISTS knowledge_relations (
                relation_id TEXT PRIMARY KEY,
                source_item_id TEXT NOT NULL,
                target_item_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT 'manual',
                confidence REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                FOREIGN KEY(target_item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                CHECK(source_item_id <> target_item_id),
                CHECK(confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_relations_source
                ON knowledge_relations(source_item_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_knowledge_relations_target
                ON knowledge_relations(target_item_id, relation_type);

            CREATE TABLE IF NOT EXISTS knowledge_collections (
                collection_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                parent_collection_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(parent_collection_id) REFERENCES knowledge_collections(collection_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_collection_items (
                collection_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(collection_id, item_id),
                FOREIGN KEY(collection_id) REFERENCES knowledge_collections(collection_id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_collection_items_item
                ON knowledge_collection_items(item_id, collection_id);

            CREATE TABLE IF NOT EXISTS knowledge_tags (
                tag_id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                color TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_item_tags (
                item_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(item_id, tag_id),
                FOREIGN KEY(item_id) REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES knowledge_tags(tag_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_item_tags_tag
                ON knowledge_item_tags(tag_id, item_id);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO app_state(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def _initialize(self) -> None:
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    self._ensure_schema(connection)

    @staticmethod
    def _item(row: sqlite3.Row) -> KnowledgeItem:
        return KnowledgeItem(
            item_id=row["item_id"],
            item_type=KnowledgeItemType(row["item_type"]),
            title=row["title"],
            summary=row["summary"],
            resource_document_id=row["resource_document_id"],
            source_uri=row["source_uri"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _relation(row: sqlite3.Row) -> KnowledgeRelation:
        return KnowledgeRelation(
            relation_id=row["relation_id"],
            source_item_id=row["source_item_id"],
            target_item_id=row["target_item_id"],
            relation_type=row["relation_type"],
            label=row["label"],
            origin=KnowledgeRelationOrigin(row["origin"]),
            confidence=row["confidence"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _collection(row: sqlite3.Row) -> KnowledgeCollection:
        return KnowledgeCollection(
            collection_id=row["collection_id"],
            name=row["name"],
            description=row["description"],
            parent_collection_id=row["parent_collection_id"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _tag(row: sqlite3.Row) -> KnowledgeTag:
        return KnowledgeTag(
            tag_id=row["tag_id"],
            name=row["name"],
            color=row["color"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_item(self, item: KnowledgeItem) -> KnowledgeItem:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_items(
                        item_id, item_type, title, summary, resource_document_id,
                        source_uri, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        item_type=excluded.item_type,
                        title=excluded.title,
                        summary=excluded.summary,
                        resource_document_id=excluded.resource_document_id,
                        source_uri=excluded.source_uri,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.item_id,
                        item.item_type.value,
                        item.title,
                        item.summary,
                        item.resource_document_id,
                        item.source_uri,
                        _json_dump(item.metadata),
                        item.created_at.isoformat(),
                        item.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge item violates repository constraints: {exc}") from exc
        stored = self.get_item(item.item_id)
        if stored is None:
            raise RuntimeError("knowledge item was not persisted")
        return stored

    def get_item(self, item_id: str) -> KnowledgeItem | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        return self._item(row) if row is not None else None

    def find_item_by_resource_document_id(self, document_id: str) -> KnowledgeItem | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_items WHERE resource_document_id = ?",
                (document_id,),
            ).fetchone()
        return self._item(row) if row is not None else None

    def list_items(
        self,
        *,
        item_type: KnowledgeItemType | None = None,
        collection_id: str | None = None,
        tag_id: str | None = None,
    ) -> list[KnowledgeItem]:
        joins: list[str] = []
        where: list[str] = []
        params: list[str] = []
        if collection_id:
            joins.append(
                "JOIN knowledge_collection_items ci ON ci.item_id = i.item_id"
            )
            where.append("ci.collection_id = ?")
            params.append(collection_id)
        if tag_id:
            joins.append("JOIN knowledge_item_tags it ON it.item_id = i.item_id")
            where.append("it.tag_id = ?")
            params.append(tag_id)
        if item_type is not None:
            where.append("i.item_type = ?")
            params.append(item_type.value)
        sql = "SELECT DISTINCT i.* FROM knowledge_items i"
        if joins:
            sql += " " + " ".join(joins)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY i.updated_at DESC, i.item_id ASC"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._item(row) for row in rows]

    def delete_item(self, item_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_items WHERE item_id = ?", (item_id,)
            )
            return cursor.rowcount > 0

    def save_relation(self, relation: KnowledgeRelation) -> KnowledgeRelation:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_relations(
                        relation_id, source_item_id, target_item_id, relation_type,
                        label, origin, confidence, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(relation_id) DO UPDATE SET
                        source_item_id=excluded.source_item_id,
                        target_item_id=excluded.target_item_id,
                        relation_type=excluded.relation_type,
                        label=excluded.label,
                        origin=excluded.origin,
                        confidence=excluded.confidence,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        relation.relation_id,
                        relation.source_item_id,
                        relation.target_item_id,
                        relation.relation_type,
                        relation.label,
                        relation.origin.value,
                        relation.confidence,
                        _json_dump(relation.metadata),
                        relation.created_at.isoformat(),
                        relation.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge relation violates repository constraints: {exc}") from exc
        stored = self.get_relation(relation.relation_id)
        if stored is None:
            raise RuntimeError("knowledge relation was not persisted")
        return stored

    def get_relation(self, relation_id: str) -> KnowledgeRelation | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_relations WHERE relation_id = ?", (relation_id,)
            ).fetchone()
        return self._relation(row) if row is not None else None

    def list_relations(self, *, item_id: str | None = None) -> list[KnowledgeRelation]:
        sql = "SELECT * FROM knowledge_relations"
        params: tuple[str, ...] = ()
        if item_id:
            sql += " WHERE source_item_id = ? OR target_item_id = ?"
            params = (item_id, item_id)
        sql += " ORDER BY updated_at DESC, relation_id ASC"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._relation(row) for row in rows]

    def delete_relation(self, relation_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_relations WHERE relation_id = ?", (relation_id,)
            )
            return cursor.rowcount > 0

    def save_collection(self, collection: KnowledgeCollection) -> KnowledgeCollection:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_collections(
                        collection_id, name, description, parent_collection_id,
                        metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collection_id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        parent_collection_id=excluded.parent_collection_id,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        collection.collection_id,
                        collection.name,
                        collection.description,
                        collection.parent_collection_id,
                        _json_dump(collection.metadata),
                        collection.created_at.isoformat(),
                        collection.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge collection violates repository constraints: {exc}") from exc
        stored = self.get_collection(collection.collection_id)
        if stored is None:
            raise RuntimeError("knowledge collection was not persisted")
        return stored

    def get_collection(self, collection_id: str) -> KnowledgeCollection | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
        return self._collection(row) if row is not None else None

    def list_collections(self) -> list[KnowledgeCollection]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_collections ORDER BY name COLLATE NOCASE, collection_id"
            ).fetchall()
        return [self._collection(row) for row in rows]

    def delete_collection(self, collection_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_collections WHERE collection_id = ?",
                (collection_id,),
            )
            return cursor.rowcount > 0

    def add_item_to_collection(self, item_id: str, collection_id: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO knowledge_collection_items(collection_id, item_id) VALUES (?, ?)",
                    (collection_id, item_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("unknown knowledge item or collection") from exc

    def remove_item_from_collection(self, item_id: str, collection_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_collection_items WHERE collection_id = ? AND item_id = ?",
                (collection_id, item_id),
            )
            return cursor.rowcount > 0

    def save_tag(self, tag: KnowledgeTag) -> KnowledgeTag:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_tags(tag_id, name, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(tag_id) DO UPDATE SET
                        name=excluded.name,
                        color=excluded.color,
                        updated_at=excluded.updated_at
                    """,
                    (
                        tag.tag_id,
                        tag.name,
                        tag.color,
                        tag.created_at.isoformat(),
                        tag.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge tag violates repository constraints: {exc}") from exc
        stored = self.get_tag(tag.tag_id)
        if stored is None:
            raise RuntimeError("knowledge tag was not persisted")
        return stored

    def get_tag(self, tag_id: str) -> KnowledgeTag | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()
        return self._tag(row) if row is not None else None

    def list_tags(self) -> list[KnowledgeTag]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_tags ORDER BY name COLLATE NOCASE, tag_id"
            ).fetchall()
        return [self._tag(row) for row in rows]

    def delete_tag(self, tag_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute("DELETE FROM knowledge_tags WHERE tag_id = ?", (tag_id,))
            return cursor.rowcount > 0

    def add_tag_to_item(self, item_id: str, tag_id: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO knowledge_item_tags(item_id, tag_id) VALUES (?, ?)",
                    (item_id, tag_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("unknown knowledge item or tag") from exc

    def remove_tag_from_item(self, item_id: str, tag_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_item_tags WHERE item_id = ? AND tag_id = ?",
                (item_id, tag_id),
            )
            return cursor.rowcount > 0


__all__ = ["KnowledgeRepository", "SCHEMA_VERSION", "SqliteKnowledgeRepository"]
