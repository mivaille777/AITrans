from backend.knowledge.domain import KnowledgeItemType
from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService


def test_semantic_card_types_round_trip_through_canonical_repository(tmp_path):
    service = KnowledgeWorkspaceService(
        SqliteKnowledgeRepository(tmp_path / "knowledge-card-domain.sqlite3")
    )

    for item_type in (
        KnowledgeItemType.EVIDENCE,
        KnowledgeItemType.INSIGHT,
        KnowledgeItemType.QUESTION,
    ):
        created = service.create_item(
            item_type=item_type,
            title=f"{item_type.value} card",
            summary="semantic card",
            metadata={
                "confidence": 0.8,
                "provenance": {"created_by": "agent", "agent_name": "test-agent"},
            },
        )

        restored = service.get_item(created.item_id)
        assert restored is not None
        assert restored.item_type is item_type
        assert restored.metadata["confidence"] == 0.8
        assert restored.metadata["provenance"]["created_by"] == "agent"
        assert service.list_items(item_type=item_type) == [restored]
