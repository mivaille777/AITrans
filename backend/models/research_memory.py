from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResearchMemoryClaimType = Literal[
    "finding",
    "method",
    "definition",
    "assumption",
    "limitation",
    "background",
    "comparison",
    "other",
]
ResearchMemoryEntityType = Literal[
    "method",
    "metric",
    "model",
    "dataset",
    "process",
    "parameter",
    "concept",
    "paper",
    "person",
    "organization",
    "other",
]


class ResearchMemoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchMemoryExtractedClaim(ResearchMemoryContract):
    text: str = Field(min_length=1, max_length=5_000)
    claim_type: ResearchMemoryClaimType = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_excerpt: str = Field(default="", max_length=4_000)


class ResearchMemoryExtractedEntity(ResearchMemoryContract):
    canonical_name: str = Field(min_length=1, max_length=500)
    entity_type: ResearchMemoryEntityType = "concept"
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=2_000)


class ResearchMemoryExtractedRelation(ResearchMemoryContract):
    subject: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=500)
    claim_index: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ResearchMemoryExtraction(ResearchMemoryContract):
    claims: list[ResearchMemoryExtractedClaim] = Field(default_factory=list, max_length=24)
    entities: list[ResearchMemoryExtractedEntity] = Field(default_factory=list, max_length=40)
    relations: list[ResearchMemoryExtractedRelation] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def validate_relation_references(self) -> "ResearchMemoryExtraction":
        names: set[str] = set()
        for entity in self.entities:
            names.add(" ".join(entity.canonical_name.casefold().split()))
            names.update(
                " ".join(alias.casefold().split())
                for alias in entity.aliases
                if alias.strip()
            )
        for relation in self.relations:
            subject = " ".join(relation.subject.casefold().split())
            target = " ".join(relation.object.casefold().split())
            if subject not in names or target not in names:
                raise ValueError("Relation subject/object must reference extracted entities.")
            if relation.claim_index is not None and relation.claim_index >= len(self.claims):
                raise ValueError("Relation claim_index must reference an extracted claim.")
        return self


class ResearchMemoryExtractionResponse(ResearchMemoryContract):
    extraction_id: str
    workspace_id: str
    note_id: str
    extractor_version: str = ""
    prompt_id: str = ""
    claim_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    entity_count: int = Field(default=0, ge=0)
    relation_count: int = Field(default=0, ge=0)
    updated_at: str = ""


class ResearchMemoryClaimResponse(ResearchMemoryContract):
    claim_id: str
    note_id: str
    claim_type: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: str


class ResearchMemoryEvidenceResponse(ResearchMemoryContract):
    evidence_id: str
    claim_id: str
    note_id: str
    excerpt: str
    start_offset: int
    end_offset: int
    source_verified: bool
    created_at: str


class ResearchMemoryEntityResponse(ResearchMemoryContract):
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    updated_at: str


class ResearchMemoryRelationResponse(ResearchMemoryContract):
    relation_id: str
    note_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    claim_id: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: str


class ResearchMemoryWorkspaceResponse(ResearchMemoryContract):
    workspace_id: str
    extraction_count: int = Field(default=0, ge=0)
    claims: list[ResearchMemoryClaimResponse] = Field(default_factory=list)
    evidence: list[ResearchMemoryEvidenceResponse] = Field(default_factory=list)
    entities: list[ResearchMemoryEntityResponse] = Field(default_factory=list)
    relations: list[ResearchMemoryRelationResponse] = Field(default_factory=list)


class ResearchMemorySearchResult(ResearchMemoryContract):
    kind: Literal["claim", "evidence", "entity", "relation"]
    item_id: str
    note_id: str = ""
    title: str = ""
    text: str
    score: float = Field(ge=0.0)
    claim_id: str = ""
    entity_id: str = ""


class ResearchMemorySearchResponse(ResearchMemoryContract):
    workspace_id: str
    query: str
    count: int = Field(default=0, ge=0)
    results: list[ResearchMemorySearchResult] = Field(default_factory=list)


__all__ = [
    "ResearchMemoryClaimResponse",
    "ResearchMemoryClaimType",
    "ResearchMemoryEntityResponse",
    "ResearchMemoryEntityType",
    "ResearchMemoryEvidenceResponse",
    "ResearchMemoryExtractedClaim",
    "ResearchMemoryExtractedEntity",
    "ResearchMemoryExtractedRelation",
    "ResearchMemoryExtraction",
    "ResearchMemoryExtractionResponse",
    "ResearchMemoryRelationResponse",
    "ResearchMemorySearchResponse",
    "ResearchMemorySearchResult",
    "ResearchMemoryWorkspaceResponse",
]
