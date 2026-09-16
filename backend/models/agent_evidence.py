from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.agent_artifacts import EvidenceRef


class EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EvidenceSourceCategory(str, Enum):
    DOCUMENT = "document"
    RESEARCH_NOTE = "research_note"
    KNOWLEDGE_ITEM = "knowledge_item"
    REVIEW_LEDGER = "review_ledger"
    USER_SUPPLIED = "user_supplied"


class EvidenceSourceStatus(str, Enum):
    FRESH = "fresh"
    LEGACY_UNKNOWN = "legacy_unknown"
    STALE = "stale"
    DETACHED = "detached"
    ORPHANED = "orphaned"
    ACCEPTED = "accepted"
    UNREVIEWED = "unreviewed"


class EvidenceLocator(EvidenceContract):
    chunk_id: str = Field(default="", max_length=256)
    page_number: int | None = Field(default=None, ge=1)
    element_id: str = Field(default="", max_length=256)
    table_id: str = Field(default="", max_length=256)
    image_id: str = Field(default="", max_length=256)
    section_path: list[str] = Field(default_factory=list, max_length=64)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    source_uri: str = Field(default="", max_length=8192)


class EvidencePacket(EvidenceContract):
    evidence_ref: EvidenceRef
    text: str = Field(default="", max_length=100_000)
    title: str = Field(default="", max_length=2_000)
    source_category: EvidenceSourceCategory
    status: EvidenceSourceStatus = EvidenceSourceStatus.LEGACY_UNKNOWN
    relevance_score: float = Field(default=0.0, ge=0.0)
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    review_status: Literal["", "unreviewed", "accepted", "rejected", "needs_review"] = ""
    machine_status: Literal["", "supported", "contested", "insufficient", "stale"] = ""
    relation_ids: list[str] = Field(default_factory=list, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> dict[str, Any]:
        return dict(value or {})


__all__ = [
    "EvidenceLocator",
    "EvidencePacket",
    "EvidenceSourceCategory",
    "EvidenceSourceStatus",
]
