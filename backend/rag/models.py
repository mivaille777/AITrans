from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RagContractModel(BaseModel):
    """Base model for stable RAG domain contracts."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeDocument(RagContractModel):
    document_id: str = Field(min_length=1)
    title: str = ""
    source_uri: str = ""
    source_kind: str = "unknown"
    mime_type: str = ""
    language: str = "unknown"
    content_hash: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSection(RagContractModel):
    heading: str = ""
    level: int = Field(default=1, ge=1, le=6)
    text: str = ""
    start_char: int = Field(default=0, ge=0)
    end_char: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_character_range(self) -> "DocumentSection":
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        return self


class DocumentPage(RagContractModel):
    page_number: int = Field(ge=1)
    text: str = ""
    start_char: int = Field(default=0, ge=0)
    end_char: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_character_range(self) -> "DocumentPage":
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        return self


DocumentModality = Literal["text", "picture", "table", "formula", "page"]


class DocumentElement(RagContractModel):
    """One addressable multimodal element extracted from a source document.

    ``surrogate_text`` is the retrieval representation. ``asset_uri`` points to
    the original visual evidence and is deliberately kept out of vector payload
    bytes so Qdrant stores only metadata, never encoded images.
    """

    element_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    modality: DocumentModality
    surrogate_text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    section_path: list[str] = Field(default_factory=list)
    caption: str = ""
    asset_uri: str = ""
    parent_id: str = ""
    related_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(RagContractModel):
    document: KnowledgeDocument
    text: str = ""
    sections: list[DocumentSection] = Field(default_factory=list)
    pages: list[DocumentPage] = Field(default_factory=list)
    elements: list[DocumentElement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(RagContractModel):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    title: str = ""
    section_heading: str = ""
    section_path: list[str] = Field(default_factory=list)
    hierarchy_level: int = Field(default=0, ge=0, le=6)
    parent_section_id: str = ""
    chunk_type: str = "paragraph_group"
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int = Field(ge=0)
    paragraph_index: int | None = Field(default=None, ge=0)
    paragraph_end_index: int | None = Field(default=None, ge=0)
    start_char: int = Field(default=0, ge=0)
    end_char: int = Field(default=0, ge=0)
    token_count: int = Field(default=0, ge=0)
    language: str = "unknown"
    source_uri: str = ""
    document_hash: str = ""
    parser_version: str = ""
    chunker_version: str = ""
    embedding_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_character_range(self) -> "DocumentChunk":
        if self.end_char < self.start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        if (
            self.paragraph_index is not None
            and self.paragraph_end_index is not None
            and self.paragraph_end_index < self.paragraph_index
        ):
            raise ValueError(
                "paragraph_end_index must be greater than or equal to paragraph_index"
            )
        return self


class RetrievalContextWindow(RagContractModel):
    """Supplemental same-section context anchored to one true retrieval hit."""

    anchor_chunk_id: str = Field(min_length=1)
    chunks: list[DocumentChunk] = Field(default_factory=list)
    text: str = ""
    token_count: int = Field(default=0, ge=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    strategy: str = "small-to-big"

    @model_validator(mode="after")
    def validate_window(self) -> "RetrievalContextWindow":
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end must not be smaller than page_start")
        if self.chunks and self.anchor_chunk_id not in {
            chunk.chunk_id for chunk in self.chunks
        }:
            raise ValueError("context window must contain its anchor chunk")
        return self


class RetrievalCandidate(RagContractModel):
    chunk: DocumentChunk
    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    rank: int | None = Field(default=None, ge=1)
    context_window: RetrievalContextWindow | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(RagContractModel):
    query: str = Field(min_length=1)
    candidates: list[RetrievalCandidate] = Field(default_factory=list)
    retrieval_strategy: str = "unresolved"
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_stable_chunk_id(
    *,
    document_hash: str,
    section_heading: str,
    chunk_index: int,
    text: str,
) -> str:
    """Build a deterministic chunk identifier from stable source attributes."""

    if not document_hash:
        raise ValueError("document_hash must not be empty")
    if chunk_index < 0:
        raise ValueError("chunk_index must be greater than or equal to zero")
    if not text:
        raise ValueError("text must not be empty")

    payload = "\x1f".join(
        (
            document_hash,
            section_heading.strip(),
            str(chunk_index),
            text,
        )
    ).encode("utf-8")
    return f"chunk_{sha256(payload).hexdigest()[:24]}"


__all__ = [
    "DocumentChunk",
    "DocumentElement",
    "DocumentModality",
    "DocumentPage",
    "DocumentSection",
    "KnowledgeDocument",
    "NormalizedDocument",
    "RagContractModel",
    "RetrievalCandidate",
    "RetrievalContextWindow",
    "RetrievalResult",
    "build_stable_chunk_id",
]
