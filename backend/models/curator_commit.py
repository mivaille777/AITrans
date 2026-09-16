from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.agent_tasks import ScopeContext


class CuratorCommitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CuratorCommitTargetResult(CuratorCommitModel):
    target_key: str = Field(min_length=1, max_length=512)
    target_kind: Literal["note", "item", "relation_proposal"]
    status: Literal["committed", "failed", "skipped"]
    object_id: str = Field(default="", max_length=256)
    error_code: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=4000)


class CuratorCommitReceipt(CuratorCommitModel):
    operation_id: str = Field(min_length=1, max_length=256)
    payload_hash: str = Field(min_length=64, max_length=64)
    artifact_id: str = Field(min_length=1, max_length=256)
    artifact_version: int = Field(ge=1)
    workspace_id: str = Field(min_length=1, max_length=256)
    status: Literal["completed", "partial", "failed", "in_progress"]
    results: list[CuratorCommitTargetResult] = Field(
        default_factory=list, max_length=2048
    )
    replayed: bool = False


class CuratorCommitRequest(CuratorCommitModel):
    artifact_id: str = Field(min_length=1, max_length=256)
    artifact_version: int = Field(default=1, ge=1)
    operation_id: str = Field(min_length=1, max_length=256)
    scope: ScopeContext
    selected_draft_ids: list[str] = Field(default_factory=list, max_length=2048)


__all__ = [
    "CuratorCommitReceipt",
    "CuratorCommitRequest",
    "CuratorCommitTargetResult",
]
