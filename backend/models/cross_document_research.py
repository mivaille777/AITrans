from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CrossDocumentResearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CrossDocumentSource(CrossDocumentResearchContract):
    document_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=1024)
    resource_url: str = Field(default="", max_length=4096)
    note_ids: list[str] = Field(default_factory=list, max_length=128)


class CrossDocumentSupport(CrossDocumentResearchContract):
    support_id: str = Field(min_length=1, max_length=160)
    kind: Literal["claim", "relation"]
    claim_id: str = Field(default="", max_length=128)
    relation_id: str = Field(default="", max_length=128)
    note_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    source_status: Literal["fresh", "legacy_unknown"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CrossDocumentAgreement(CrossDocumentResearchContract):
    cluster_id: str = Field(min_length=1, max_length=64)
    kind: Literal["claim", "relation"]
    key: str = Field(min_length=1, max_length=4000)
    statement: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] = Field(default_factory=list, min_length=2, max_length=128)
    supports: list[CrossDocumentSupport] = Field(default_factory=list, min_length=2, max_length=256)

    @property
    def document_count(self) -> int:
        return len(self.document_ids)


class CrossDocumentAlternative(CrossDocumentResearchContract):
    target_entity_id: str = Field(min_length=1, max_length=128)
    target_name: str = Field(min_length=1, max_length=1024)
    document_ids: list[str] = Field(default_factory=list, min_length=1, max_length=128)
    supports: list[CrossDocumentSupport] = Field(default_factory=list, min_length=1, max_length=256)


class CrossDocumentDisagreement(CrossDocumentResearchContract):
    group_id: str = Field(min_length=1, max_length=64)
    subject_entity_id: str = Field(min_length=1, max_length=128)
    subject_name: str = Field(min_length=1, max_length=1024)
    predicate: str = Field(min_length=1, max_length=256)
    document_ids: list[str] = Field(default_factory=list, min_length=2, max_length=128)
    alternatives: list[CrossDocumentAlternative] = Field(
        default_factory=list,
        min_length=2,
        max_length=32,
    )


class CrossDocumentAnalysis(CrossDocumentResearchContract):
    workspace_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4000)
    document_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    claim_support_count: int = Field(default=0, ge=0)
    relation_support_count: int = Field(default=0, ge=0)
    agreement_count: int = Field(default=0, ge=0)
    disagreement_count: int = Field(default=0, ge=0)
    sources: list[CrossDocumentSource] = Field(default_factory=list, max_length=256)
    agreements: list[CrossDocumentAgreement] = Field(default_factory=list, max_length=128)
    disagreements: list[CrossDocumentDisagreement] = Field(default_factory=list, max_length=64)


__all__ = [
    "CrossDocumentAgreement",
    "CrossDocumentAlternative",
    "CrossDocumentAnalysis",
    "CrossDocumentDisagreement",
    "CrossDocumentSource",
    "CrossDocumentSupport",
]
