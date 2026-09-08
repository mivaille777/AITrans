from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Any


class KnowledgeV2Repository:
    """SQLite repository for Knowledge 2.0 semantic objects."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path).expanduser().resolve()
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_cards_v2 (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                content_json TEXT DEFAULT '{}',
                confidence REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_evidence_v2 (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                chunk_id TEXT,
                quote TEXT NOT NULL,
                page INTEGER,
                section TEXT
            );
            CREATE TABLE IF NOT EXISTS knowledge_relations_v2 (
                id TEXT PRIMARY KEY,
                source_card_id TEXT NOT NULL,
                target_card_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                created_by TEXT DEFAULT 'agent'
            );
            CREATE TABLE IF NOT EXISTS knowledge_agent_events_v2 (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id TEXT NOT NULL,
                input_json TEXT DEFAULT '{}',
                output_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """)
            conn.commit()

    def create_card(self, card: dict[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO knowledge_cards_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (card['id'], card['type'], card['title'], card.get('summary', ''),
                 self.dumps(card.get('content', {})), card.get('confidence', 0),
                 card['created_at'], card['updated_at'])
            )
            conn.commit()
        return card

    def list_cards(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM knowledge_cards_v2 ORDER BY created_at DESC").fetchall()
        return [self._card_row(row) for row in rows]

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM knowledge_cards_v2 WHERE id=?", (card_id,)).fetchone()
        return self._card_row(row) if row else None

    def create_relation(self, relation: dict[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO knowledge_relations_v2 VALUES (?, ?, ?, ?, ?, ?)",
                (relation['id'], relation['source_card_id'], relation['target_card_id'],
                 relation['relation_type'], relation.get('confidence', 0),
                 relation.get('created_by', 'agent'))
            )
            conn.commit()
        return relation

    def get_graph(self) -> dict[str, list[Any]]:
        return {"nodes": self.list_cards(), "edges": self.list_relations()}

    def list_relations(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM knowledge_relations_v2").fetchall()
        return [dict(row) for row in rows]

    def record_agent_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO knowledge_agent_events_v2 VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event['id'], event['agent_name'], event['action'], event['target_id'],
                 self.dumps(event.get('input', {})), self.dumps(event.get('output', {})),
                 event['created_at'])
            )
            conn.commit()
        return event

    def list_agent_events(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM knowledge_agent_events_v2 ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _card_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data['content'] = json.loads(data.pop('content_json') or '{}')
        return data

    @staticmethod
    def dumps(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False)
