from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ArtifactKind(str, Enum):
    DOCUMENT_ANALYSIS = "document_analysis"
    COMPARISON = "comparison"
    OUTLINE = "outline"
    MANUSCRIPT_SECTION = "manuscript_section"
    REVISION = "revision"
    KNOWLEDGE_DRAFT = "knowledge_draft"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    REVOKED = "revoked"


def _json_safe(value: Any, *, path: str = "content") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            result[key] = _json_safe(item, path=f"{path}.{key}")
        return result
    raise ValueError(
        f"{path} must contain only JSON-compatible values; "
        f"got {type(value).__name__}"
    )


class EvidenceRef(ArtifactModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    source_type: str = Field(min_length=1, max_length=64)
    source_version: str = Field(default="", max_length=256)
    source_hash: str = Field(default="", max_length=256)
    locator: dict[str, Any] = Field(default_factory=dict)

    @field_validator("locator", mode="before")
    @classmethod
    def validate_locator(cls, value: Any) -> dict[str, Any]:
        return dict(_json_safe(value or {}, path="locator"))


class ArtifactRef(ArtifactModel):
    artifact_id: str = Field(min_length=1, max_length=256)
    version: int = Field(ge=1)
    kind: ArtifactKind
    content_hash: str = Field(min_length=1, max_length=128)


class ClaimRecord(ArtifactModel):
    claim_id: str = Field(min_length=1, max_length=256)
    statement: str = Field(min_length=1, max_length=50_000)
    category: Literal["fact", "interpretation", "suggestion", "user_supplied"] = "fact"
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)


class SourceCoverage(ArtifactModel):
    complete: bool = False
    covered_refs: list[str] = Field(default_factory=list, max_length=256)
    missing_refs: list[str] = Field(default_factory=list, max_length=256)
    notes: list[str] = Field(default_factory=list, max_length=128)


class VerificationIssue(ArtifactModel):
    code: str = Field(min_length=1, max_length=128)
    severity: Literal["info", "warning", "error"] = "warning"
    message: str = Field(min_length=1, max_length=4000)
    field: str = Field(default="", max_length=256)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)


class VerificationReport(ArtifactModel):
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    checked_fields: list[str] = Field(default_factory=list, max_length=256)
    source_ids: list[str] = Field(default_factory=list, max_length=512)
    citation_count: int = Field(default=0, ge=0)
    issues: list[VerificationIssue] = Field(default_factory=list, max_length=512)


class Artifact(ArtifactModel):
    artifact_id: str = Field(min_length=1, max_length=256)
    version: int = Field(default=1, ge=1)
    producer_task_id: str = Field(min_length=1, max_length=256)
    kind: ArtifactKind
    scope_ref: str = Field(min_length=1, max_length=256)
    content: dict[str, Any] = Field(default_factory=dict)
    content_ref: str = Field(default="", max_length=2048)
    claims: list[ClaimRecord] = Field(default_factory=list, max_length=512)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=512)
    lineage: list[ArtifactRef] = Field(default_factory=list, max_length=256)
    source_coverage: SourceCoverage = Field(default_factory=SourceCoverage)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_report: VerificationReport = Field(default_factory=VerificationReport)
    content_hash: str = Field(default="", max_length=128)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, value: Any) -> dict[str, Any]:
        return dict(_json_safe(value or {}, path="content"))

    def hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(
            mode="json",
            exclude={"content_hash", "created_at"},
        )
        return dict(_json_safe(payload, path="artifact"))

    def computed_hash(self) -> str:
        encoded = json.dumps(
            self.hash_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def bind_content_hash(self) -> Artifact:
        expected = self.computed_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("artifact content_hash does not match normalized payload")
        object.__setattr__(self, "content_hash", expected)
        return self

    def ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.artifact_id,
            version=self.version,
            kind=self.kind,
            content_hash=self.content_hash,
        )


class DocumentAnalysisArtifact(Artifact):
    kind: Literal[ArtifactKind.DOCUMENT_ANALYSIS] = ArtifactKind.DOCUMENT_ANALYSIS
    document_id: str = Field(min_length=1, max_length=256)
    document_version: str = Field(default="", max_length=256)
    research_questions: list[str] = Field(default_factory=list, max_length=64)
    contributions: list[str] = Field(default_factory=list, max_length=128)
    methods: list[str] = Field(default_factory=list, max_length=128)
    datasets: list[str] = Field(default_factory=list, max_length=128)
    experiments: list[str] = Field(default_factory=list, max_length=256)
    limitations: list[str] = Field(default_factory=list, max_length=128)
    open_questions: list[str] = Field(default_factory=list, max_length=128)


class ComparisonCell(ArtifactModel):
    dimension: str = Field(min_length=1, max_length=512)
    source_label: str = Field(min_length=1, max_length=512)
    value: str = Field(default="", max_length=20_000)
    conditions: str = Field(default="", max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    unknown: bool = False


class ResearchHypothesis(ArtifactModel):
    statement: str = Field(min_length=1, max_length=20_000)
    basis_ids: list[str] = Field(default_factory=list, max_length=128)
    status: Literal["hypothesis"] = "hypothesis"


class ReferenceRecord(ArtifactModel):
    source_id: str = Field(min_length=1, max_length=256)
    title: str = Field(default="", max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=128)
    year: str = Field(default="", max_length=16)
    doi: str = Field(default="", max_length=512)
    evidence_ids: list[str] = Field(default_factory=list, max_length=512)
    missing_fields: list[str] = Field(default_factory=list, max_length=32)


class ComparisonArtifact(Artifact):
    kind: Literal[ArtifactKind.COMPARISON] = ArtifactKind.COMPARISON
    dimensions: list[str] = Field(default_factory=list, max_length=128)
    cells: list[ComparisonCell] = Field(default_factory=list, max_length=1024)
    consensus: list[str] = Field(default_factory=list, max_length=128)
    conflicts: list[str] = Field(default_factory=list, max_length=128)
    supported_limitations: list[str] = Field(default_factory=list, max_length=128)
    research_directions: list[str] = Field(default_factory=list, max_length=128)
    research_hypotheses: list[ResearchHypothesis] = Field(
        default_factory=list, max_length=128
    )


class OutlineSection(ArtifactModel):
    section_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=1000)
    objective: str = Field(default="", max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)


class OutlineArtifact(Artifact):
    kind: Literal[ArtifactKind.OUTLINE] = ArtifactKind.OUTLINE
    title: str = Field(default="", max_length=1000)
    writing_goal: str = Field(default="", max_length=20_000)
    sections: list[OutlineSection] = Field(default_factory=list, max_length=256)
    references: list[ReferenceRecord] = Field(default_factory=list, max_length=512)
    missing_inputs: list[str] = Field(default_factory=list, max_length=128)


class ManuscriptSectionArtifact(Artifact):
    kind: Literal[ArtifactKind.MANUSCRIPT_SECTION] = ArtifactKind.MANUSCRIPT_SECTION
    section_id: str = Field(min_length=1, max_length=256)
    title: str = Field(default="", max_length=1000)
    markdown: str = Field(default="", max_length=200_000)
    paragraph_ids: list[str] = Field(default_factory=list, max_length=2048)
    claim_source_map: dict[str, list[str]] = Field(default_factory=dict)
    references: list[ReferenceRecord] = Field(default_factory=list, max_length=512)
    missing_inputs: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("claim_source_map", mode="before")
    @classmethod
    def validate_claim_source_map(cls, value: Any) -> dict[str, list[str]]:
        normalized = _json_safe(value or {}, path="claim_source_map")
        return {str(key): [str(item) for item in items] for key, items in dict(normalized).items()}


class RevisionChange(ArtifactModel):
    paragraph_id: str = Field(min_length=1, max_length=256)
    before_hash: str = Field(default="", max_length=128)
    replacement_markdown: str = Field(default="", max_length=100_000)
    rationale: str = Field(default="", max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    category: Literal["fact", "interpretation", "suggestion", "user_supplied"] = (
        "suggestion"
    )


class RevisionArtifact(Artifact):
    kind: Literal[ArtifactKind.REVISION] = ArtifactKind.REVISION
    target_section_id: str = Field(min_length=1, max_length=256)
    base_version: int = Field(ge=1)
    allowed_paragraph_ids: list[str] = Field(default_factory=list, max_length=2048)
    changes: list[RevisionChange] = Field(default_factory=list, max_length=2048)


class KnowledgeItemDraft(ArtifactModel):
    draft_id: str = Field(min_length=1, max_length=256)
    item_type: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=50_000)
    source_ids: list[str] = Field(default_factory=list, max_length=128)
    duplicate_candidate_ids: list[str] = Field(default_factory=list, max_length=128)
    subtype: str = Field(default="", max_length=128)
    source_quote: str = Field(default="", max_length=50_000)
    ai_content: str = Field(default="", max_length=50_000)
    user_note: str = Field(default="", max_length=20_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    existing_item_id: str = Field(default="", max_length=256)
    expected_version: int = Field(default=0, ge=0)
    expected_content_hash: str = Field(default="", max_length=128)

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, value: Any) -> dict[str, Any]:
        return dict(_json_safe(value or {}, path="knowledge_item.metadata"))


class NoteDraft(ArtifactModel):
    """A reviewable Research Note change with source and authorship separated."""

    draft_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    source_quote: str = Field(min_length=1, max_length=20_000)
    ai_content: str = Field(default="", max_length=30_000)
    user_note: str = Field(default="", max_length=20_000)
    resource_uri: str = Field(default="", max_length=8192)
    resource_title: str = Field(default="", max_length=1024)
    section_heading: str = Field(default="", max_length=1024)
    existing_note_id: str = Field(default="", max_length=256)
    expected_version: int = Field(default=0, ge=0)
    expected_content_hash: str = Field(default="", max_length=128)


class KnowledgeRelationDraft(ArtifactModel):
    source_draft_or_item_id: str = Field(min_length=1, max_length=256)
    target_draft_or_item_id: str = Field(min_length=1, max_length=256)
    relation_type: str = Field(min_length=1, max_length=128)
    rationale: str = Field(default="", max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)


class RelationProposal(KnowledgeRelationDraft):
    proposal_id: str = Field(min_length=1, max_length=256)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: Literal["pending"] = "pending"


class KnowledgeDraftArtifact(Artifact):
    kind: Literal[ArtifactKind.KNOWLEDGE_DRAFT] = ArtifactKind.KNOWLEDGE_DRAFT
    workspace_id: str = Field(min_length=1, max_length=256)
    notes: list[NoteDraft] = Field(default_factory=list, max_length=512)
    items: list[KnowledgeItemDraft] = Field(default_factory=list, max_length=512)
    relations: list[KnowledgeRelationDraft] = Field(default_factory=list, max_length=1024)
    relation_proposals: list[RelationProposal] = Field(default_factory=list, max_length=1024)
    warnings: list[str] = Field(default_factory=list, max_length=128)


ARTIFACT_MODEL_BY_KIND: dict[ArtifactKind, type[Artifact]] = {
    ArtifactKind.DOCUMENT_ANALYSIS: DocumentAnalysisArtifact,
    ArtifactKind.COMPARISON: ComparisonArtifact,
    ArtifactKind.OUTLINE: OutlineArtifact,
    ArtifactKind.MANUSCRIPT_SECTION: ManuscriptSectionArtifact,
    ArtifactKind.REVISION: RevisionArtifact,
    ArtifactKind.KNOWLEDGE_DRAFT: KnowledgeDraftArtifact,
}


def artifact_from_payload(payload: dict[str, Any]) -> Artifact:
    kind = ArtifactKind(str(payload.get("kind", "")))
    return ARTIFACT_MODEL_BY_KIND[kind].model_validate(payload)


__all__ = [
    "ARTIFACT_MODEL_BY_KIND",
    "Artifact",
    "ArtifactKind",
    "ArtifactRef",
    "ClaimRecord",
    "ComparisonArtifact",
    "ComparisonCell",
    "DocumentAnalysisArtifact",
    "EvidenceRef",
    "KnowledgeDraftArtifact",
    "KnowledgeItemDraft",
    "KnowledgeRelationDraft",
    "ManuscriptSectionArtifact",
    "NoteDraft",
    "OutlineArtifact",
    "OutlineSection",
    "ReferenceRecord",
    "RelationProposal",
    "ResearchHypothesis",
    "RevisionArtifact",
    "RevisionChange",
    "SourceCoverage",
    "VerificationIssue",
    "VerificationReport",
    "VerificationStatus",
    "artifact_from_payload",
]
