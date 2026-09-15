import sqlite3
from pathlib import Path

from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.v2_repository import KnowledgeV2Repository


def _card(card_id: str, card_type: str, title: str) -> dict[str, object]:
    return {
        "id": card_id,
        "type": card_type,
        "title": title,
        "summary": f"Summary for {title}",
        "content": {"key": card_id},
        "confidence": 0.9,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_knowledge_v2_repository_uses_canonical_storage(tmp_path: Path):
    storage_path = tmp_path / "knowledge.db"
    repo = KnowledgeV2Repository(storage_path)

    assert repo.create_card(_card("card_source", "concept", "Agentic RAG"))["id"] == "card_source"
    repo.create_card(_card("card_target", "insight", "Bounded tool use"))

    relation = {
        "id": "relation_test",
        "source_card_id": "card_source",
        "target_card_id": "card_target",
        "relation_type": "similar",
        "confidence": 0.8,
        "created_by": "agent",
    }
    repo.create_relation(relation)

    canonical = SqliteKnowledgeRepository(storage_path)
    source = canonical.get_item("card_source")
    stored_relation = canonical.get_relation("relation_test")

    assert source is not None
    assert source.item_type.value == "concept"
    assert source.metadata["confidence"] == 0.9
    assert source.metadata["content"] == {"key": "card_source"}
    assert stored_relation is not None
    assert stored_relation.source_item_id == "card_source"
    assert stored_relation.target_item_id == "card_target"
    assert stored_relation.origin.value == "ai"
    assert len(repo.get_graph()["edges"]) == 1

    with sqlite3.connect(storage_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "knowledge_items" in tables
    assert "knowledge_relations" in tables
    assert "knowledge_agent_events_v2" in tables
    assert "knowledge_cards_v2" not in tables
    assert "knowledge_relations_v2" not in tables


def test_knowledge_v2_repository_migrates_existing_legacy_tables(tmp_path: Path):
    storage_path = tmp_path / "legacy.db"
    with sqlite3.connect(storage_path) as conn:
        conn.executescript(
            """
            CREATE TABLE knowledge_cards_v2 (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                content_json TEXT DEFAULT '{}',
                confidence REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE knowledge_relations_v2 (
                id TEXT PRIMARY KEY,
                source_card_id TEXT NOT NULL,
                target_card_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                created_by TEXT DEFAULT 'agent'
            );
            """
        )
        conn.execute(
            "INSERT INTO knowledge_cards_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy_concept",
                "concept",
                "Legacy concept",
                "legacy summary",
                '{"source":"legacy"}',
                0.7,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_cards_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy_evidence",
                "evidence",
                "Legacy evidence",
                "legacy evidence summary",
                "{}",
                0.8,
                "2026-01-02T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_relations_v2 VALUES (?, ?, ?, ?, ?, ?)",
            (
                "legacy_relation",
                "legacy_evidence",
                "legacy_concept",
                "support",
                0.75,
                "agent",
            ),
        )

    repo = KnowledgeV2Repository(storage_path)
    canonical = SqliteKnowledgeRepository(storage_path)

    migrated = repo.get_card("legacy_concept")
    relation = canonical.get_relation("legacy_relation")

    assert migrated is not None
    assert migrated["content"] == {"source": "legacy"}
    assert migrated["confidence"] == 0.7
    assert canonical.get_item("legacy_evidence") is not None
    assert relation is not None
    assert relation.relation_type == "support"
    assert len(repo.get_graph()["nodes"]) == 2
    assert len(repo.get_graph()["edges"]) == 1
