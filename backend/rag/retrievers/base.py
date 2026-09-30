from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from uuid import uuid4

from backend.rag.models import ChannelHit, RetrievalCandidate
from backend.rag.stores.base import VectorSearchFilter, effective_document_ids


@dataclass(frozen=True)
class RetrievalRequest:
    """Snapshot shared scope; None preserves explicitly legacy global retrieval."""

    query: str
    top_k: int
    filters: VectorSearchFilter = field(default_factory=VectorSearchFilter)
    allowed_document_ids: tuple[str, ...] | None = None
    active_generations: Mapping[str, str | None] | None = None
    query_vector: tuple[float, ...] | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if not self.query.strip() or self.top_k <= 0:
            raise ValueError("retrieval query and top_k must be valid")
        filters = self.filters.model_copy(deep=True)
        scope = effective_document_ids(
            filters,
            list(self.allowed_document_ids)
            if self.allowed_document_ids is not None
            else None,
        )
        if self.active_generations is not None:
            generations = dict(self.active_generations)
            scope = sorted(
                set(generations)
                if scope is None
                else set(scope).intersection(generations)
            )
            object.__setattr__(
                self, "active_generations", MappingProxyType(generations)
            )
        object.__setattr__(self, "filters", filters)
        object.__setattr__(
            self, "allowed_document_ids", tuple(scope) if scope is not None else None
        )
        if self.query_vector is not None:
            object.__setattr__(self, "query_vector", tuple(self.query_vector))

    def search_filters(self) -> VectorSearchFilter:
        filters = self.filters.model_copy(deep=True)
        if self.allowed_document_ids is not None:
            filters.document_ids = list(self.allowed_document_ids)
        return filters


@runtime_checkable
class RetrieverChannel(Protocol):
    def retrieve(self, request: RetrievalRequest) -> list[RetrievalCandidate]: ...


def record_channel_hits(
    request: RetrievalRequest,
    candidates: list[RetrievalCandidate],
    *,
    channel: str,
    score_field: str,
) -> list[RetrievalCandidate]:
    """Reject out-of-scope/stale hits and attach original channel provenance."""
    results = []
    for position, candidate in enumerate(candidates, start=1):
        document_id = candidate.chunk.document_id
        generation = candidate.chunk.metadata.get("index_generation") or None
        if candidate.index_generation is not None:
            if generation is not None and generation != candidate.index_generation:
                raise ValueError("candidate generation disagrees with source chunk")
            generation = candidate.index_generation
        if (
            request.allowed_document_ids is not None
            and document_id not in request.allowed_document_ids
        ):
            continue
        if request.active_generations is not None and (
            document_id not in request.active_generations
            or generation != request.active_generations[document_id]
        ):
            continue
        hit = ChannelHit(
            channel=channel,
            raw_score=getattr(candidate, score_field),
            rank=candidate.rank or position,
        )
        results.append(
            candidate.model_copy(
                update={
                    "channel_hits": [*candidate.channel_hits, hit],
                    "index_generation": generation,
                    "trace_id": request.trace_id,
                }
            )
        )
    return results
