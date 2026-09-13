from __future__ import annotations

import sqlite3

# These names are retained only so existing databases can be recognized and
# migrated by KnowledgeV2Repository. New databases no longer create them.
LEGACY_KNOWLEDGE_V2_TABLES = (
    "knowledge_cards_v2",
    "knowledge_evidence_v2",
    "knowledge_relations_v2",
)

# Agent events do not yet have a canonical Knowledge workspace equivalent, so
# this is the only V2-owned table still created for new databases.
KNOWLEDGE_V2_TABLES = ("knowledge_agent_events_v2",)


def ensure_knowledge_v2_schema(connection: sqlite3.Connection) -> None:
    """Ensure only the remaining V2 compatibility audit table exists.

    Knowledge cards and relations are now persisted in the canonical
    ``knowledge_items`` and ``knowledge_relations`` tables. Existing legacy V2
    tables are left untouched and are used only as migration sources.
    """

    connection.execute(
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
