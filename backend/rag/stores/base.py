from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from backend.rag.models import DocumentChunk, RetrievalCandidate


class VectorSearchFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(default_factory=list)
    source_kind: str | None = None
    language: str | None = None
    metadata: dict[str, str | int | bool] = Field(default_factory=dict)
    # Reference lists are useful only for bibliography-specific requests.  They
    # otherwise consume context with citation strings instead of source facts.
    exclude_references: bool = True


def effective_document_ids(
    filters: VectorSearchFilter | None,
    allowed_document_ids: list[str] | None,
) -> list[str] | None:
    """Intersect request filters with the caller's resolved access allowlist.

    ``None`` keeps the legacy unscoped contract. An empty allowlist or empty
    intersection is an explicit deny-all result.
    """

    requested = (
        set(filters.document_ids)
        if filters is not None and filters.document_ids
        else None
    )
    allowed = set(allowed_document_ids) if allowed_document_ids is not None else None
    if requested is None and allowed is None:
        return None
    if requested is None:
        return sorted(allowed or set())
    if allowed is None:
        return sorted(requested)
    return sorted(requested.intersection(allowed))


_REFERENCE_HEADING = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*|[ivxlcdm]+)[.)]?\s+)?"
    r"(?:references?|bibliography|works cited|reference list)\s*[:：.]?\s*$",
    re.IGNORECASE,
)


def is_reference_chunk(chunk: DocumentChunk) -> bool:
    """Return whether a chunk is bibliographic material, including legacy data.

    New structured indexes set ``metadata.section_kind``.  The heading/text
    checks keep the retrieval policy safe while old indexes are awaiting a
    Docling reindex.
    """

    metadata = chunk.metadata
    if str(metadata.get("section_kind", "")).casefold() == "references":
        return True
    if chunk.chunk_type in {"reference_group", "reference_entry"}:
        return True
    if any(
        _REFERENCE_HEADING.fullmatch(heading)
        for heading in (chunk.section_heading, *chunk.section_path)
    ):
        return True
    # Legacy unstructured chunks may start with a bibliography heading. A
    # mention such as "Fixed-PID reference" is a body fact, never a heading.
    first_line = next(
        (line.strip() for line in chunk.text.splitlines() if line.strip()), ""
    )
    return bool(_REFERENCE_HEADING.fullmatch(first_line))


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        generation_id: str | None = None,
    ) -> None: ...

    def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        allowed_document_ids: list[str] | None = None,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]: ...

    def delete_document(
        self, document_id: str, *, generation_id: str | None = None
    ) -> None: ...

    def delete_chunks(
        self, chunk_ids: list[str], *, generation_id: str | None = None
    ) -> None: ...

    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None
    ) -> DocumentChunk | None: ...

    def list_chunks(
        self, *, generation_id: str | None = None
    ) -> list[DocumentChunk]: ...


__all__ = [
    "VectorSearchFilter",
    "VectorStore",
    "effective_document_ids",
    "is_reference_chunk",
]
