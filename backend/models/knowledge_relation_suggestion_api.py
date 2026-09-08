from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge.domain import (
    KnowledgeRelation,
    KnowledgeRelationSuggestion,
    KnowledgeRelationSuggestionStatus,
)


class KnowledgeRelationSuggestionApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeRelationSuggestionGenerateRequest(KnowledgeRelationSuggestionApiModel):
    focus_item_id: str = Field(min_length=1, max_length=128)
    candidate_item_ids: list[str] = Field(default_factory=list, max_length=64)
    max_suggestions: int = Field(default=4, ge=1, le=6)


class KnowledgeRelationSuggestionListResponse(KnowledgeRelationSuggestionApiModel):
    total: int = Field(ge=0)
    suggestions: list[KnowledgeRelationSuggestion] = Field(default_factory=list)


class KnowledgeRelationSuggestionDecisionResponse(KnowledgeRelationSuggestionApiModel):
    suggestion: KnowledgeRelationSuggestion
    relation: KnowledgeRelation | None = None


class KnowledgeRelationSuggestionStatusFilter(KnowledgeRelationSuggestionApiModel):
    status: KnowledgeRelationSuggestionStatus | None = None


__all__ = [
    "KnowledgeRelationSuggestionDecisionResponse",
    "KnowledgeRelationSuggestionGenerateRequest",
    "KnowledgeRelationSuggestionListResponse",
    "KnowledgeRelationSuggestionStatusFilter",
]
