from __future__ import annotations

import re
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


_REFERENCE_HEADING = re.compile(
    r"(?:^|\s)(?:references?|bibliography|works cited|reference list)(?:$|\s)",
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
    headings = " ".join([chunk.section_heading, *chunk.section_path])
    if _REFERENCE_HEADING.search(headings):
        return True
    prefix = chunk.text[:240].replace("\n", " ")
    return bool(_REFERENCE_HEADING.search(prefix))


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
    ) -> None: ...

    def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[RetrievalCandidate]: ...

    def delete_document(self, document_id: str) -> None: ...

    def delete_chunks(self, chunk_ids: list[str]) -> None: ...

    def get_chunk(self, chunk_id: str) -> DocumentChunk | None: ...


__all__ = ["VectorSearchFilter", "VectorStore", "is_reference_chunk"]
