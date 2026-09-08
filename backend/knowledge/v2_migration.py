from __future__ import annotations

import sqlite3


KNOWLEDGE_V2_TABLES = (
    "knowledge_cards_v2",
    "knowledge_evidence_v2",
    "knowledge_relations_v2",
    "knowledge_agent_events_v2",
)


def ensure_knowledge_v2_schema(connection: sqlite3.Connection) -> None:
    """Create Knowledge 2.0 tables without touching existing tables."""
    connection.executescript(
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
