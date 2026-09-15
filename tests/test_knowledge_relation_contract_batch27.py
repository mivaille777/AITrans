from __future__ import annotations

import pytest

from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeRelationOrigin,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRepository,
)


def test_manual_relation_is_directional_canonical_context(tmp_path) -> None:
    service = KnowledgeWorkspaceService(
        SqliteKnowledgeRepository(tmp_path / "knowledge.sqlite3")
    )
    insight = service.create_item(
        item_type=KnowledgeItemType.INSIGHT,
        title="LLM refinement insight",
    )
    evidence = service.create_item(
        item_type=KnowledgeItemType.EVIDENCE,
        title="PID tuning evidence",
    )

    relation = service.create_relation(
        source_item_id=insight.item_id,
        target_item_id=evidence.item_id,
        relation_type="supports",
        label="User-confirmed support edge",
    )

    assert relation.source_item_id == insight.item_id
    assert relation.target_item_id == evidence.item_id
    assert relation.relation_type == "supports"
    assert relation.origin is KnowledgeRelationOrigin.MANUAL
    assert relation.label == "User-confirmed support edge"


def test_manual_relation_rejects_self_loop_and_duplicate_edge(tmp_path) -> None:
    service = KnowledgeWorkspaceService(
        SqliteKnowledgeRepository(tmp_path / "knowledge.sqlite3")
    )
    first = service.create_item(item_type=KnowledgeItemType.CONCEPT, title="First")
    second = service.create_item(item_type=KnowledgeItemType.CONCEPT, title="Second")

    with pytest.raises(ValueError, match="same item"):
        service.create_relation(
            source_item_id=first.item_id,
            target_item_id=first.item_id,
            relation_type="related_to",
        )

    service.create_relation(
        source_item_id=first.item_id,
        target_item_id=second.item_id,
        relation_type="supports",
    )
    with pytest.raises(ValueError, match="already exists"):
        service.create_relation(
            source_item_id=first.item_id,
            target_item_id=second.item_id,
            relation_type="supports",
        )

    reverse = service.create_relation(
        source_item_id=second.item_id,
        target_item_id=first.item_id,
        relation_type="supports",
    )
    assert reverse.source_item_id == second.item_id
    assert reverse.target_item_id == first.item_id
