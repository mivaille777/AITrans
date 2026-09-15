from backend.knowledge.v2_repository import KnowledgeV2Repository
from backend.knowledge.v2_service import KnowledgeV2Service


def test_knowledge_v2_service_can_initialize(tmp_path):
    repository = KnowledgeV2Repository(tmp_path / "knowledge.db")
    service = KnowledgeV2Service(repository)

    card = service.create_card(
        card_type="concept",
        title="Agentic RAG",
        summary="Agent controlled retrieval workflow",
    )

    assert card["type"] == "concept"
    assert card["title"] == "Agentic RAG"
