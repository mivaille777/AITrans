from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType


class KnowledgeWorkspaceApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeItemCreateRequest(KnowledgeWorkspaceApiModel):
    item_type: KnowledgeItemType
    title: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=50_000)
    source_uri: str = Field(default="", max_length=8192)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeItemUpdateRequest(KnowledgeWorkspaceApiModel):
    item_type: KnowledgeItemType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=50_000)
    source_uri: str | None = Field(default=None, max_length=8192)
    metadata: dict[str, Any] | None = None


class KnowledgeItemListResponse(KnowledgeWorkspaceApiModel):
    total: int = Field(ge=0)
    items: list[KnowledgeItem] = Field(default_factory=list)


class KnowledgeItemDeleteResponse(KnowledgeWorkspaceApiModel):
    item_id: str
    deleted: bool


__all__ = [
    "KnowledgeItemCreateRequest",
    "KnowledgeItemDeleteResponse",
    "KnowledgeItemListResponse",
    "KnowledgeItemUpdateRequest",
    "KnowledgeWorkspaceApiModel",
]
