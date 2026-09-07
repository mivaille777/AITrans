from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge.board_domain import KnowledgeBoard, KnowledgeBoardNode


class KnowledgeBoardApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeBoardCreateRequest(KnowledgeBoardApiModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)


class KnowledgeBoardListResponse(KnowledgeBoardApiModel):
    total: int = Field(ge=0)
    boards: list[KnowledgeBoard] = Field(default_factory=list)


class KnowledgeBoardSnapshotResponse(KnowledgeBoardApiModel):
    board: KnowledgeBoard
    nodes: list[KnowledgeBoardNode] = Field(default_factory=list)


class KnowledgeBoardNodeUpsertRequest(KnowledgeBoardApiModel):
    x: float
    y: float
    width: float = Field(default=248.0, ge=180.0, le=720.0)
    height: float = Field(default=156.0, ge=100.0, le=600.0)
    collapsed: bool = False
    z_index: int = Field(default=0, ge=0, le=1_000_000)


class KnowledgeBoardDeleteResponse(KnowledgeBoardApiModel):
    board_id: str
    deleted: bool


class KnowledgeBoardNodeDeleteResponse(KnowledgeBoardApiModel):
    board_id: str
    item_id: str
    deleted: bool


__all__ = [
    "KnowledgeBoardCreateRequest",
    "KnowledgeBoardDeleteResponse",
    "KnowledgeBoardListResponse",
    "KnowledgeBoardNodeDeleteResponse",
    "KnowledgeBoardNodeUpsertRequest",
    "KnowledgeBoardSnapshotResponse",
]
