from __future__ import annotations

from time import perf_counter

from backend.rag.config import RagRetrievalConfig
from backend.rag.embeddings.base import EmbeddingProvider
from backend.rag.exceptions import RagRetrievalError
from backend.rag.fusion import rrf_fuse
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.rerankers.base import RerankerProvider
from backend.rag.small_to_big import SmallToBigContextExpander
from backend.rag.sparse.store import SparseRetriever
from backend.rag.stores.base import VectorSearchFilter, VectorStore
from backend.rag.structure_retrieval import order_structural_candidates


class RetrievalService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        sparse_retriever: SparseRetriever,
        config: RagRetrievalConfig | None = None,
        reranker: RerankerProvider | None = None,
    ) -> None:
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._sparse = sparse_retriever
        self._config = config or RagRetrievalConfig()
        self._reranker = reranker

    def retrieve(
        self,
        query: str,
        *,
        filters: VectorSearchFilter | None = None,
        section_hints: tuple[str, ...] = (),
        final_top_k: int | None = None,
        include_references: bool = False,
    ) -> RetrievalResult:
        if not query or not query.strip():
            raise RagRetrievalError("retrieval query must not be empty")
        desired_top_k = final_top_k or self._config.final_top_k
        if desired_top_k <= 0:
            raise ValueError("final_top_k must be positive")

        started = perf_counter()
        effective_filters = filters or VectorSearchFilter()
        if include_references and effective_filters.exclude_references:
            effective_filters = effective_filters.model_copy(
                update={"exclude_references": False}
            )

        dense: list[RetrievalCandidate] = []
        sparse: list[RetrievalCandidate] = []
        structural: list[RetrievalCandidate] = []
        dense_error = ""
        sparse_error = ""
        structural_error = ""
        embedding_ms = 0.0
        dense_ms = 0.0
        try:
            embedding_started = perf_counter()
            vector = self._embedding.embed_query(query)
            embedding_ms = (perf_counter() - embedding_started) * 1000
            dense_started = perf_counter()
            dense = self._vector_store.search(
                vector,
                top_k=self._config.dense_top_k,
                filters=effective_filters,
            )
            dense_ms = (perf_counter() - dense_started) * 1000
        except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
            dense_error = str(exc) or exc.__class__.__name__

        sparse_started = perf_counter()
        try:
            sparse = self._sparse.search(
                query,
                self._config.sparse_top_k,
                effective_filters,
            )
        except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
            sparse_error = str(exc) or exc.__class__.__name__
        sparse_ms = (perf_counter() - sparse_started) * 1000

        structural_ms = 0.0
        search_sections = getattr(self._sparse, "search_sections", None)
        if section_hints and callable(search_sections):
            structural_started = perf_counter()
            try:
                structural = search_sections(
                    section_hints,
                    max(self._config.fusion_top_k, desired_top_k),
                    effective_filters,
                )
            except Exception as exc:  # noqa: BLE001 - structural recall is additive
                structural_error = str(exc) or exc.__class__.__name__
            structural_ms = (perf_counter() - structural_started) * 1000

        if dense_error and sparse_error and not structural:
            raise RagRetrievalError(
                f"dense and sparse retrieval failed: dense={dense_error}; sparse={sparse_error}"
            )
        fusion_started = perf_counter()
        candidates = rrf_fuse(
            [ranked for ranked in (dense, sparse, structural) if ranked],
            limit=max(self._config.fusion_top_k, desired_top_k),
        )
        fusion_ms = (perf_counter() - fusion_started) * 1000
        fusion_count = len(candidates)
        strategy = self._strategy(
            dense_error=dense_error,
            sparse_error=sparse_error,
            structural=structural,
        )
        fallback_reason = "; ".join(
            item for item in (dense_error, sparse_error, structural_error) if item
        )
        reranker_applied = False
        reranker_fallback_reason = ""
        rerank_ms = 0.0
        if self._reranker is not None:
            rerank_started = perf_counter()
            try:
                rerank_limit = (
                    len(candidates)
                    if section_hints
                    else min(desired_top_k, len(candidates))
                )
                candidates = self._reranker.rerank(
                    query,
                    candidates,
                    top_k=max(1, rerank_limit),
                )
                reranker_applied = True
            except Exception as exc:  # noqa: BLE001 - RRF fallback is intentional
                reranker_fallback_reason = str(exc) or exc.__class__.__name__
            rerank_ms = (perf_counter() - rerank_started) * 1000

        candidates = self._finalize_candidates(
            candidates,
            section_hints=section_hints,
            limit=desired_top_k,
        )

        small_to_big_ms = 0.0
        small_to_big_error = ""
        small_to_big_metadata = {
            "small_to_big_expanded_count": 0,
            "small_to_big_neighbor_count": 0,
        }
        section_neighbors = getattr(self._sparse, "section_neighbors", None)
        if self._config.small_to_big_enabled and callable(section_neighbors):
            expansion_started = perf_counter()
            try:
                candidates, small_to_big_metadata = SmallToBigContextExpander(
                    neighbor_lookup=section_neighbors,
                    config=self._config,
                ).expand(candidates)
            except Exception as exc:  # noqa: BLE001 - context expansion is additive
                small_to_big_error = str(exc) or exc.__class__.__name__
            small_to_big_ms = (perf_counter() - expansion_started) * 1000

        return RetrievalResult(
            query=query,
            candidates=candidates,
            retrieval_strategy=strategy,
            elapsed_ms=(perf_counter() - started) * 1000,
            metadata={
                "dense_count": len(dense),
                "sparse_count": len(sparse),
                "structural_count": len(structural),
                "fusion_count": fusion_count,
                "final_count": len(candidates),
                "embedding_ms": embedding_ms,
                "dense_search_ms": dense_ms,
                "sparse_search_ms": sparse_ms,
                "structural_search_ms": structural_ms,
                "fusion_ms": fusion_ms,
                "rerank_ms": rerank_ms,
                "small_to_big_ms": small_to_big_ms,
                "fallback_reason": fallback_reason,
                "reranker_applied": reranker_applied,
                "reranker_fallback_reason": reranker_fallback_reason,
                "structural_section_hints": list(section_hints),
                "small_to_big_enabled": self._config.small_to_big_enabled,
                "small_to_big_error": small_to_big_error,
                **small_to_big_metadata,
            },
        )

    @staticmethod
    def _strategy(
        *,
        dense_error: str,
        sparse_error: str,
        structural: list[RetrievalCandidate],
    ) -> str:
        if structural:
            if dense_error and sparse_error:
                return "structural-only"
            return "hybrid+structural"
        if dense_error:
            return "sparse-only"
        if sparse_error:
            return "dense-only"
        return "hybrid"

    @staticmethod
    def _finalize_candidates(
        candidates: list[RetrievalCandidate],
        *,
        section_hints: tuple[str, ...],
        limit: int,
    ) -> list[RetrievalCandidate]:
        selected = candidates
        if section_hints:
            selected, _matching_count = order_structural_candidates(
                candidates,
                section_hints,
            )
        return [
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(selected[:limit], start=1)
        ]


__all__ = ["RetrievalService"]
