from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge.domain import KnowledgeRelation, KnowledgeRelationOrigin


class KnowledgeRelationApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeRelationCreateRequest(KnowledgeRelationApiModel):
    source_item_id: str = Field(min_length=1, max_length=128)
    target_item_id: str = Field(min_length=1, max_length=128)
    relation_type: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=500)
    origin: KnowledgeRelationOrigin = KnowledgeRelationOrigin.MANUAL
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeRelationUpdateRequest(KnowledgeRelationApiModel):
    relation_type: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeRelationListResponse(KnowledgeRelationApiModel):
    total: int = Field(ge=0)
    relations: list[KnowledgeRelation] = Field(default_factory=list)


class KnowledgeRelationDeleteResponse(KnowledgeRelationApiModel):
    relation_id: str
    deleted: bool


__all__ = [
    "KnowledgeRelationCreateRequest",
    "KnowledgeRelationDeleteResponse",
    "KnowledgeRelationListResponse",
    "KnowledgeRelationUpdateRequest",
]
