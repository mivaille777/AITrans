from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeV2Model(BaseModel):
    """API/storage boundary models for Knowledge 2.0 entities."""


class KnowledgeCardModel(KnowledgeV2Model):
    id: str
    type: str
    title: str
    summary: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime


class KnowledgeEvidenceModel(KnowledgeV2Model):
    id: str
    document_id: str
    chunk_id: str | None = None
    quote: str
    page: int | None = None
    section: str | None = None


class KnowledgeRelationModel(KnowledgeV2Model):
    id: str
    source_card_id: str
    target_card_id: str
    relation_type: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_by: str = "agent"


class KnowledgeAgentEventModel(KnowledgeV2Model):
    id: str
    agent_name: str
    action: str
    target_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


__all__ = [
    "KnowledgeAgentEventModel",
    "KnowledgeCardModel",
    "KnowledgeEvidenceModel",
    "KnowledgeRelationModel",
]
