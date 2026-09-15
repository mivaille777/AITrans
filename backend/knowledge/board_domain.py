from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeBoardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class KnowledgeBoard(KnowledgeBoardModel):
    board_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeBoardNode(KnowledgeBoardModel):
    board_id: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    x: float = 0.0
    y: float = 0.0
    width: float = Field(default=248.0, ge=180.0, le=720.0)
    height: float = Field(default=156.0, ge=100.0, le=600.0)
    collapsed: bool = False
    z_index: int = Field(default=0, ge=0, le=1_000_000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


__all__ = ["KnowledgeBoard", "KnowledgeBoardModel", "KnowledgeBoardNode", "utc_now"]
