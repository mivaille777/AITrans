from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from pydantic import Field

from app.research.memory import ResearchMemoryEntityDraft
from backend.rag.models import RagContractModel
from backend.rag.source_span import SourceSpan

GRAPH_SCHEMA_VERSION = 1


def normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class GraphEntity(RagContractModel):
    entity_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class RelationSource(RagContractModel):
    chunk_id: str = Field(min_length=1)
    source_span: SourceSpan


class GraphRelation(RagContractModel):
    relation_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    extractor_version: str = Field(min_length=1)
    sources: list[RelationSource] = Field(min_length=1)


class GraphGeneration(RagContractModel):
    scope_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    chunk_ids: list[str] = Field(min_length=1)
    status: str = "ready"


@dataclass(frozen=True)
class GroundedRelation:
    source_index: int
    target_index: int
    predicate: str
    confidence: float
    source_span: SourceSpan


@dataclass(frozen=True)
class ChunkGraphExtraction:
    entities: tuple[ResearchMemoryEntityDraft, ...] = ()
    relations: tuple[GroundedRelation, ...] = ()
    rejected: tuple[str, ...] = ()
