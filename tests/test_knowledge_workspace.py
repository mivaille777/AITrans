from __future__ import annotations

import sqlite3

import pytest

from backend.knowledge import (
    KnowledgeItemType,
    KnowledgeRelationOrigin,
    KnowledgeWorkspaceService,
    SqliteKnowledgeRepository,
)


def build_service(tmp_path) -> KnowledgeWorkspaceService:
    return KnowledgeWorkspaceService(
        SqliteKnowledgeRepository(tmp_path / "knowledge_workspace.sqlite3")
    )


def test_items_and_relations_survive_repository_restart(tmp_path) -> None:
    service = build_service(tmp_path)
    paper = service.create_item(
        item_type=KnowledgeItemType.PAPER,
        title="Safe Bayesian Optimization",
        metadata={"authors": ["A. Researcher"], "year": 2026},
    )
    note = service.create_item(
        item_type=KnowledgeItemType.NOTE,
        title="Safety constraint notes",
    )
    relation = service.create_relation(
        source_item_id=note.item_id,
        target_item_id=paper.item_id,
        relation_type="derived from",
        origin=KnowledgeRelationOrigin.MANUAL,
    )

    reopened = build_service(tmp_path)
    assert reopened.get_item(paper.item_id) == paper
    assert reopened.get_item(note.item_id) == note
    stored_relations = reopened.list_relations(item_id=paper.item_id)
    assert [item.relation_id for item in stored_relations] == [relation.relation_id]
    assert stored_relations[0].relation_type == "derived_from"


def test_document_resource_mapping_is_idempotent(tmp_path) -> None:
    service = build_service(tmp_path)
    first = service.ensure_document_resource(
        document_id="doc-123",
        title="Imported paper",
        source_uri="file:///tmp/paper.pdf",
        source_type="pdf",
    )
    second = service.ensure_document_resource(
        document_id="doc-123",
        title="A later parser title",
        source_uri="file:///tmp/paper.pdf",
        source_type="pdf",
    )

    assert second.item_id == first.item_id
    assert len(service.list_items()) == 1
    assert first.resource_document_id == "doc-123"
    assert first.metadata["source_type"] == "pdf"


def test_collection_and_tag_filters_use_memberships(tmp_path) -> None:
    service = build_service(tmp_path)
    paper = service.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    note = service.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    collection = service.create_collection(name="Bayesian Optimization")
    tag = service.create_tag(name="Safe BO")

    service.add_item_to_collection(
        item_id=paper.item_id,
        collection_id=collection.collection_id,
    )
    service.add_tag_to_item(item_id=paper.item_id, tag_id=tag.tag_id)

    collection_items = service.list_items(collection_id=collection.collection_id)
    tag_items = service.list_items(tag_id=tag.tag_id)
    notes = service.list_items(item_type=KnowledgeItemType.NOTE)
    assert [item.item_id for item in collection_items] == [paper.item_id]
    assert [item.item_id for item in tag_items] == [paper.item_id]
    assert [item.item_id for item in notes] == [note.item_id]


def test_delete_item_cascades_relations_and_memberships(tmp_path) -> None:
    service = build_service(tmp_path)
    paper = service.create_item(item_type=KnowledgeItemType.PAPER, title="Paper")
    note = service.create_item(item_type=KnowledgeItemType.NOTE, title="Note")
    relation = service.create_relation(
        source_item_id=note.item_id,
        target_item_id=paper.item_id,
        relation_type="explains",
    )
    collection = service.create_collection(name="Research")
    tag = service.create_tag(name="Important")
    service.add_item_to_collection(
        item_id=paper.item_id,
        collection_id=collection.collection_id,
    )
    service.add_tag_to_item(item_id=paper.item_id, tag_id=tag.tag_id)

    assert service.delete_item(paper.item_id) is True
    assert service.get_relation(relation.relation_id) is None
    assert service.list_items(collection_id=collection.collection_id) == []
    assert service.list_items(tag_id=tag.tag_id) == []


def test_relation_requires_existing_distinct_items(tmp_path) -> None:
    service = build_service(tmp_path)
    item = service.create_item(item_type=KnowledgeItemType.CONCEPT, title="RAG")

    with pytest.raises(ValueError, match="same item"):
        service.create_relation(
            source_item_id=item.item_id,
            target_item_id=item.item_id,
            relation_type="related_to",
        )

    with pytest.raises(ValueError, match="target knowledge item"):
        service.create_relation(
            source_item_id=item.item_id,
            target_item_id="missing",
            relation_type="related_to",
        )


def test_schema_enables_foreign_keys_and_wal(tmp_path) -> None:
    path = tmp_path / "knowledge_workspace.sqlite3"
    SqliteKnowledgeRepository(path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        version = connection.execute(
            "SELECT value FROM app_state WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == "1"
    finally:
        connection.close()
