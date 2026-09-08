from pathlib import Path

from backend.knowledge.v2_repository import KnowledgeV2Repository


def test_knowledge_v2_repository_crud(tmp_path: Path):
    repo = KnowledgeV2Repository(tmp_path / "knowledge.db")

    card = {
        "id": "card_test",
        "type": "concept",
        "title": "Agentic RAG",
        "summary": "agent driven retrieval",
        "content": {"key": "value"},
        "confidence": 0.9,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    assert repo.create_card(card)["id"] == "card_test"
    assert repo.get_card("card_test")["title"] == "Agentic RAG"
    assert len(repo.list_cards()) == 1

    relation = {
        "id": "relation_test",
        "source_card_id": "card_test",
        "target_card_id": "card_test",
        "relation_type": "similar",
        "confidence": 0.8,
        "created_by": "agent",
    }

    repo.create_relation(relation)
    assert len(repo.get_graph()["edges"]) == 1
