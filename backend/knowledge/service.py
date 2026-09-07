from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.knowledge.domain import (
    KnowledgeCollection,
    KnowledgeItem,
    KnowledgeItemType,
    KnowledgeRelation,
    KnowledgeRelationOrigin,
    KnowledgeTag,
    utc_now,
)
from backend.knowledge.repository import KnowledgeRepository


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class KnowledgeWorkspaceService:
    """Application boundary for card-first knowledge management.

    The service owns semantic knowledge objects and their user-visible
    relationships. Parsed chunks, embeddings and vector-store lifecycle remain
    owned by the RAG subsystem and are referenced only through
    ``resource_document_id``.
    """

    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def create_item(
        self,
        *,
        item_type: KnowledgeItemType,
        title: str,
        summary: str = "",
        resource_document_id: str | None = None,
        source_uri: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeItem:
        item = KnowledgeItem(
            item_id=_new_id("ki"),
            item_type=item_type,
            title=title.strip(),
            summary=summary,
            resource_document_id=(resource_document_id or "").strip() or None,
            source_uri=source_uri.strip(),
            metadata=dict(metadata or {}),
        )
        return self._repository.save_item(item)

    def ensure_document_resource(
        self,
        *,
        document_id: str,
        title: str,
        source_uri: str,
        source_type: str = "",
    ) -> KnowledgeItem:
        normalized_document_id = document_id.strip()
        if not normalized_document_id:
            raise ValueError("document_id must not be empty")
        existing = self._repository.find_item_by_resource_document_id(normalized_document_id)
        if existing is not None:
            return existing
        return self.create_item(
            item_type=KnowledgeItemType.DOCUMENT,
            title=title.strip() or "Untitled document",
            resource_document_id=normalized_document_id,
            source_uri=source_uri,
            metadata={"source_type": source_type.strip().lower()},
        )

    def get_item(self, item_id: str) -> KnowledgeItem | None:
        return self._repository.get_item(item_id)

    def list_items(
        self,
        *,
        item_type: KnowledgeItemType | None = None,
        collection_id: str | None = None,
        tag_id: str | None = None,
    ) -> list[KnowledgeItem]:
        return self._repository.list_items(
            item_type=item_type,
            collection_id=collection_id,
            tag_id=tag_id,
        )

    def update_item(
        self,
        item_id: str,
        *,
        item_type: KnowledgeItemType | None = None,
        title: str | None = None,
        summary: str | None = None,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeItem | None:
        existing = self.get_item(item_id)
        if existing is None:
            return None
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if item_type is not None:
            updates["item_type"] = item_type
        if title is not None:
            normalized_title = title.strip()
            if not normalized_title:
                raise ValueError("title must not be empty")
            updates["title"] = normalized_title
        if summary is not None:
            updates["summary"] = summary
        if source_uri is not None:
            updates["source_uri"] = source_uri.strip()
        if metadata is not None:
            updates["metadata"] = dict(metadata)
        return self._repository.save_item(existing.model_copy(update=updates))

    def delete_item(self, item_id: str) -> bool:
        return self._repository.delete_item(item_id)

    def create_relation(
        self,
        *,
        source_item_id: str,
        target_item_id: str,
        relation_type: str,
        label: str = "",
        origin: KnowledgeRelationOrigin = KnowledgeRelationOrigin.MANUAL,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRelation:
        if source_item_id == target_item_id:
            raise ValueError("knowledge relation cannot target the same item")
        if self.get_item(source_item_id) is None:
            raise ValueError("source knowledge item does not exist")
        if self.get_item(target_item_id) is None:
            raise ValueError("target knowledge item does not exist")
        relation = KnowledgeRelation(
            relation_id=_new_id("kr"),
            source_item_id=source_item_id,
            target_item_id=target_item_id,
            relation_type=relation_type,
            label=label,
            origin=origin,
            confidence=confidence,
            metadata=dict(metadata or {}),
        )
        return self._repository.save_relation(relation)

    def get_relation(self, relation_id: str) -> KnowledgeRelation | None:
        return self._repository.get_relation(relation_id)

    def list_relations(self, *, item_id: str | None = None) -> list[KnowledgeRelation]:
        return self._repository.list_relations(item_id=item_id)

    def delete_relation(self, relation_id: str) -> bool:
        return self._repository.delete_relation(relation_id)

    def create_collection(
        self,
        *,
        name: str,
        description: str = "",
        parent_collection_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeCollection:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("collection name must not be empty")
        if parent_collection_id and self._repository.get_collection(parent_collection_id) is None:
            raise ValueError("parent knowledge collection does not exist")
        collection = KnowledgeCollection(
            collection_id=_new_id("kc"),
            name=normalized_name,
            description=description,
            parent_collection_id=parent_collection_id,
            metadata=dict(metadata or {}),
        )
        return self._repository.save_collection(collection)

    def list_collections(self) -> list[KnowledgeCollection]:
        return self._repository.list_collections()

    def delete_collection(self, collection_id: str) -> bool:
        return self._repository.delete_collection(collection_id)

    def add_item_to_collection(self, *, item_id: str, collection_id: str) -> None:
        if self.get_item(item_id) is None:
            raise ValueError("knowledge item does not exist")
        if self._repository.get_collection(collection_id) is None:
            raise ValueError("knowledge collection does not exist")
        self._repository.add_item_to_collection(item_id, collection_id)

    def remove_item_from_collection(self, *, item_id: str, collection_id: str) -> bool:
        return self._repository.remove_item_from_collection(item_id, collection_id)

    def create_tag(self, *, name: str, color: str = "") -> KnowledgeTag:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("tag name must not be empty")
        return self._repository.save_tag(
            KnowledgeTag(tag_id=_new_id("kt"), name=normalized_name, color=color.strip())
        )

    def list_tags(self) -> list[KnowledgeTag]:
        return self._repository.list_tags()

    def delete_tag(self, tag_id: str) -> bool:
        return self._repository.delete_tag(tag_id)

    def add_tag_to_item(self, *, item_id: str, tag_id: str) -> None:
        if self.get_item(item_id) is None:
            raise ValueError("knowledge item does not exist")
        if self._repository.get_tag(tag_id) is None:
            raise ValueError("knowledge tag does not exist")
        self._repository.add_tag_to_item(item_id, tag_id)

    def remove_tag_from_item(self, *, item_id: str, tag_id: str) -> bool:
        return self._repository.remove_tag_from_item(item_id, tag_id)


__all__ = ["KnowledgeWorkspaceService"]
