from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MemoryKind(str, Enum):
    READING_GOAL = "reading_goal"
    RESEARCH_DECISION = "research_decision"
    WRITING_STYLE = "writing_style"
    TERMINOLOGY = "terminology"
    CURATION_PREFERENCE = "curation_preference"
    PROJECT_REFERENCE = "project_reference"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REVOKED = "revoked"


class MemoryItem(MemoryModel):
    item_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    kind: MemoryKind
    status: MemoryStatus
    version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=30_000)
    content_hash: str = Field(min_length=64, max_length=64)
    source_type: Literal["explicit_user", "verified_artifact", "persistent_object"]
    source_ref: str = Field(min_length=1, max_length=512)
    audience: list[str] = Field(default_factory=list, max_length=16)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("audience", mode="before")
    @classmethod
    def normalize_audience(cls, value: Any) -> list[str]:
        return sorted(
            {str(item).strip() for item in (value or []) if str(item).strip()}
        )


class MemoryReference(MemoryModel):
    item_id: str
    version: int = Field(ge=1)
    kind: MemoryKind
    workspace_id: str = ""
    content_hash: str


class MemoryPacket(MemoryModel):
    status: Literal["ready", "empty", "temporary", "invalidated", "unavailable"]
    snapshot_id: str = ""
    profile_id: str
    scope_ref: str
    workspace_id: str = ""
    references: list[MemoryReference] = Field(default_factory=list)
    role_projections: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    invalidated_item_ids: list[str] = Field(default_factory=list)
    reason_code: str = ""


class MemoryCandidate(MemoryModel):
    operation_id: str = Field(min_length=1, max_length=256)
    profile_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=30_000)
    source_ref: str = Field(min_length=1, max_length=512)
    audience: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreateRequest(MemoryModel):
    operation_id: str = Field(min_length=1, max_length=256)
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=30_000)
    workspace_id: str = Field(default="", max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateRequest(MemoryModel):
    operation_id: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=30_000)
    metadata: dict[str, Any] | None = None
    activate: bool = False


class MemoryForgetRequest(MemoryModel):
    expected_version: int = Field(ge=1)


class MemoryListResponse(MemoryModel):
    items: list[MemoryItem] = Field(default_factory=list)


__all__ = [
    "MemoryCandidate",
    "MemoryCreateRequest",
    "MemoryForgetRequest",
    "MemoryItem",
    "MemoryKind",
    "MemoryListResponse",
    "MemoryPacket",
    "MemoryReference",
    "MemoryStatus",
    "MemoryUpdateRequest",
    "utc_now",
]
