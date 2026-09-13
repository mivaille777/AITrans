from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class KnowledgeItemType(str, Enum):
    PAPER = "paper"
    NOTE = "note"
    CONCEPT = "concept"
    HIGHLIGHT = "highlight"
    EVIDENCE = "evidence"
    INSIGHT = "insight"
    QUESTION = "question"
    DOCUMENT = "document"
    WEB = "web"


class KnowledgeRelationOrigin(str, Enum):
    MANUAL = "manual"
    IMPORTED = "imported"
    AI = "ai"
    CITATION = "citation"
    RAG = "rag"


class KnowledgeRelationSuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReadingStatus(str, Enum):
    UNREAD = "unread"
    READING = "reading"
    READ = "read"


KNOWN_RELATION_TYPES = frozenset(
    {
        "related_to",
        "supports",
        "contradicts",
        "explains",
        "extends",
        "uses",
        "derived_from",
        "cites",
        "reading_note",
        "custom",
    }
)

AI_SUGGESTIBLE_RELATION_TYPES = frozenset(
    {
        "related_to",
        "supports",
        "contradicts",
        "explains",
        "extends",
        "uses",
    }
)


class PaperMetadata(KnowledgeDomainModel):
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=9999)
    journal: str = ""
    doi: str = ""
    citation_key: str = ""
    reading_status: ReadingStatus = ReadingStatus.UNREAD
    rating: int | None = Field(default=None, ge=1, le=5)


class KnowledgeItem(KnowledgeDomainModel):
    item_id: str = Field(min_length=1, max_length=128)
    item_type: KnowledgeItemType
    title: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=50_000)
    resource_document_id: str | None = Field(default=None, max_length=256)
    source_uri: str = Field(default="", max_length=8192)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeRelation(KnowledgeDomainModel):
    relation_id: str = Field(min_length=1, max_length=128)
    source_item_id: str = Field(min_length=1, max_length=128)
    target_item_id: str = Field(min_length=1, max_length=128)
    relation_type: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=500)
    origin: KnowledgeRelationOrigin = KnowledgeRelationOrigin.MANUAL
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold().replace(" ", "_")
        if not normalized:
            raise ValueError("relation_type must not be empty")
        return normalized


class KnowledgeRelationSuggestion(KnowledgeDomainModel):
    suggestion_id: str = Field(min_length=1, max_length=128)
    focus_item_id: str = Field(min_length=1, max_length=128)
    source_item_id: str = Field(min_length=1, max_length=128)
    target_item_id: str = Field(min_length=1, max_length=128)
    relation_type: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=500)
    rationale: str = Field(default="", max_length=8_000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_item_ids: list[str] = Field(default_factory=list, max_length=8)
    status: KnowledgeRelationSuggestionStatus = KnowledgeRelationSuggestionStatus.PENDING
    accepted_relation_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold().replace(" ", "_")
        if not normalized:
            raise ValueError("relation_type must not be empty")
        return normalized


class KnowledgeCollection(KnowledgeDomainModel):
    collection_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    parent_collection_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeTag(KnowledgeDomainModel):
    tag_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    color: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


__all__ = [
    "AI_SUGGESTIBLE_RELATION_TYPES",
    "KNOWN_RELATION_TYPES",
    "KnowledgeCollection",
    "KnowledgeDomainModel",
    "KnowledgeItem",
    "KnowledgeItemType",
    "KnowledgeRelation",
    "KnowledgeRelationOrigin",
    "KnowledgeRelationSuggestion",
    "KnowledgeRelationSuggestionStatus",
    "KnowledgeTag",
    "PaperMetadata",
    "ReadingStatus",
    "utc_now",
]
