from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.research_memory import ResearchMemorySearchResult

ResearchMemorySourceStatus = Literal[
    "fresh",
    "legacy_unknown",
    "stale",
    "orphaned",
    "detached",
]


class ResearchMemoryReliabilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchMemoryConflictGroup(ResearchMemoryReliabilityContract):
    group_id: str = Field(min_length=1, max_length=64)
    workspace_id: str = Field(min_length=1, max_length=128)
    subject_entity_id: str = Field(min_length=1, max_length=128)
    predicate: str = Field(min_length=1, max_length=256)
    target_entity_ids: list[str] = Field(default_factory=list, min_length=2, max_length=32)
    relation_ids: list[str] = Field(default_factory=list, min_length=2, max_length=64)
    claim_ids: list[str] = Field(default_factory=list, max_length=64)
    note_ids: list[str] = Field(default_factory=list, max_length=64)


class ResearchMemoryHitReliability(ResearchMemoryReliabilityContract):
    source_status: ResearchMemorySourceStatus = "legacy_unknown"
    source_note_ids: list[str] = Field(default_factory=list, max_length=64)
    groundable: bool = False
    conflicted: bool = False
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    conflict_group_ids: list[str] = Field(default_factory=list, max_length=32)


class ResearchMemoryReliableSearchResult(ResearchMemoryReliabilityContract):
    result: ResearchMemorySearchResult
    reliability: ResearchMemoryHitReliability


class ResearchMemoryReliabilitySummary(ResearchMemoryReliabilityContract):
    total_hit_count: int = Field(default=0, ge=0)
    fresh_hit_count: int = Field(default=0, ge=0)
    legacy_unknown_hit_count: int = Field(default=0, ge=0)
    stale_hit_count: int = Field(default=0, ge=0)
    orphaned_hit_count: int = Field(default=0, ge=0)
    detached_hit_count: int = Field(default=0, ge=0)
    conflicted_hit_count: int = Field(default=0, ge=0)
    groundable_hit_count: int = Field(default=0, ge=0)
    provenance_resolved_count: int = Field(default=0, ge=0)
    groundable_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance_resolution_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    stale_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    orphaned_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    detached_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)


__all__ = [
    "ResearchMemoryConflictGroup",
    "ResearchMemoryHitReliability",
    "ResearchMemoryReliabilitySummary",
    "ResearchMemoryReliableSearchResult",
    "ResearchMemorySourceStatus",
]
