from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import VectorSearchFilter


@runtime_checkable
class VisualVectorStore(Protocol):
    @property
    def dimension(self) -> int: ...
    @property
    def collection_name(self) -> str: ...
    def ensure_collection(self) -> None: ...
    def has_document(
        self,
        document_id: str,
        *,
        index_version: str,
        generation_id: str | None = None,
        content_hash: str | None = None,
    ) -> bool: ...
    def replace_document(
        self,
        document_id: str,
        chunks: list[DocumentChunk],
        vectors: list[list[list[float]]],
        *,
        index_version: str,
    ) -> None: ...
    def search(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]: ...
    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None
    ) -> DocumentChunk | None: ...
    def list_chunks(self) -> list[DocumentChunk]: ...
    def delete_document(self, document_id: str) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class VisualBenchmarkStore(VisualVectorStore, Protocol):
    def estimate_candidate_count(
        self, filters=None, *, active_generations=None
    ) -> int: ...
    def search_full_maxsim(
        self, query, *, top_k: int, filters=None, active_generations=None
    ): ...
    def fixed_prefetch_store(self, prefetch_k: int) -> VisualBenchmarkStore: ...
