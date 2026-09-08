from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock


class KnowledgeV2Repository:
    """Incremental SQLite persistence for Knowledge 2.0.

    This repository intentionally shares the existing knowledge database. It
    only owns semantic graph entities and never duplicates RAG chunks or
    embeddings.
    """

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
            conn.executescript(
                """
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
                """
            )
            conn.commit()

    def health_check(self) -> bool:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1").fetchone() is not None

    @staticmethod
    def dumps(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False)
