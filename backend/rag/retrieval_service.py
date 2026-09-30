from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from time import perf_counter

from backend.rag.config import RagRetrievalConfig
from backend.rag.embeddings.base import EmbeddingFingerprint, EmbeddingProvider
from backend.rag.exceptions import RagRetrievalError
from backend.rag.fusion import rrf_fuse
from backend.rag.index_manifest import IndexManifest
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.rerankers.base import RerankerProvider
from backend.rag.retrievers.base import RetrievalRequest, record_channel_hits
from backend.rag.retrievers.bm25 import BM25Retriever
from backend.rag.retrievers.vector import VectorRetriever
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
        manifest: IndexManifest | None = None,
    ) -> None:
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._sparse = sparse_retriever
        self._config = config or RagRetrievalConfig()
        self._reranker = reranker
        self._manifest = manifest

    def retrieve(
        self,
        query: str,
        *,
        filters: VectorSearchFilter | None = None,
        section_hints: tuple[str, ...] = (),
        final_top_k: int | None = None,
        include_references: bool = False,
        dense_enabled: bool = True,
        sparse_enabled: bool = True,
        structural_enabled: bool = True,
        reranker_enabled: bool = True,
        small_to_big_enabled: bool | None = None,
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
        active_generations = self._resolve_active_generations(effective_filters)
        request = RetrievalRequest(
            query=query,
            top_k=self._config.dense_top_k,
            filters=effective_filters,
            active_generations=active_generations,
        )
        effective_filters = request.search_filters()

        dense: list[RetrievalCandidate] = []
        sparse: list[RetrievalCandidate] = []
        structural: list[RetrievalCandidate] = []
        use_structural = structural_enabled and bool(section_hints)
        use_small_to_big = (
            self._config.small_to_big_enabled
            if small_to_big_enabled is None
            else small_to_big_enabled
        )
        if not dense_enabled and not sparse_enabled and not use_structural:
            raise ValueError("at least one retrieval channel must be enabled")
        dense_error = ""
        sparse_error = ""
        structural_error = ""
        embedding_ms = 0.0
        dense_ms = 0.0
        sparse_ms = 0.0
        dense_incompatible_document_ids: list[str] = []
        if dense_enabled:
            try:
                embedding_started = perf_counter()
                vector = self._embedding.embed_query(query)
                embedding_ms = (perf_counter() - embedding_started) * 1000
                dense_started = perf_counter()
                dense_generations = active_generations
                fingerprint = getattr(self._embedding, "fingerprint", None)
                if (
                    self._manifest is not None
                    and active_generations is not None
                    and isinstance(fingerprint, EmbeddingFingerprint)
                ):
                    dense_generations = dict(active_generations)
                    for document_id in active_generations:
                        record = self._manifest.get(document_id)
                        if (
                            record is None
                            or record.embedding_fingerprint != fingerprint.as_dict()
                        ):
                            dense_incompatible_document_ids.append(document_id)
                            dense_generations.pop(document_id)
                    if dense_incompatible_document_ids and not dense_generations:
                        raise RagRetrievalError(
                            "embedding fingerprint changed; reindex required"
                        )
                dense = VectorRetriever(self._vector_store).retrieve(
                    replace(
                        request,
                        query_vector=tuple(vector),
                        active_generations=dense_generations,
                    )
                )
                dense_ms = (perf_counter() - dense_started) * 1000
            except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
                dense_error = str(exc) or exc.__class__.__name__

        if sparse_enabled:
            sparse_started = perf_counter()
            try:
                sparse = BM25Retriever(self._sparse).retrieve(
                    replace(request, top_k=self._config.sparse_top_k)
                )
            except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
                sparse_error = str(exc) or exc.__class__.__name__
            sparse_ms = (perf_counter() - sparse_started) * 1000

        structural_ms = 0.0
        search_sections = getattr(self._sparse, "search_sections", None)
        if use_structural and callable(search_sections):
            structural_started = perf_counter()
            try:
                section_kwargs = {
                    "filters": effective_filters,
                }
                if active_generations is not None:
                    structural = search_sections(
                        section_hints,
                        max(self._config.fusion_top_k, desired_top_k),
                        active_generations=active_generations,
                        **section_kwargs,
                    )
                else:
                    structural = search_sections(
                        section_hints,
                        max(self._config.fusion_top_k, desired_top_k),
                        effective_filters,
                    )
                structural = record_channel_hits(
                    request,
                    structural,
                    channel="structural",
                    score_field="sparse_score",
                )
            except Exception as exc:  # noqa: BLE001 - structural recall is additive
                structural_error = str(exc) or exc.__class__.__name__
            structural_ms = (perf_counter() - structural_started) * 1000

        if (
            (dense_error or sparse_error or structural_error)
            and (not dense_enabled or dense_error)
            and (not sparse_enabled or sparse_error)
            and not structural
        ):
            raise RagRetrievalError(
                "all enabled retrieval channels failed (dense and sparse): "
                f"dense={dense_error}; sparse={sparse_error}; structural={structural_error}"
            )
        fusion_started = perf_counter()
        candidates = rrf_fuse(
            [ranked for ranked in (dense, sparse, structural) if ranked],
            limit=max(self._config.fusion_top_k, desired_top_k),
        )
        fusion_ms = (perf_counter() - fusion_started) * 1000
        fusion_candidates = list(candidates)
        fusion_count = len(fusion_candidates)
        pre_rerank_chunk_ids = [
            candidate.chunk.chunk_id for candidate in fusion_candidates
        ]
        strategy = self._strategy(
            dense_error=dense_error,
            sparse_error=sparse_error,
            structural=structural,
            dense_enabled=dense_enabled,
            sparse_enabled=sparse_enabled,
        )
        fallback_reason = "; ".join(
            item for item in (dense_error, sparse_error, structural_error) if item
        )
        reranker_applied = False
        reranker_fallback_reason = ""
        rerank_ms = 0.0
        rerank_input_chunk_ids: list[str] = []
        candidates = fusion_candidates
        if reranker_enabled and self._reranker is not None and fusion_candidates:
            if section_hints:
                # Structural queries intentionally expose the whole fused pool so
                # section-priority semantics are preserved after reranking.
                rerank_candidates = fusion_candidates
            else:
                configured_rerank_k = max(
                    desired_top_k,
                    self._config.effective_rerank_candidate_k,
                )
                rerank_candidates = fusion_candidates[
                    : min(configured_rerank_k, len(fusion_candidates))
                ]
            rerank_input_chunk_ids = [
                candidate.chunk.chunk_id for candidate in rerank_candidates
            ]
            rerank_started = perf_counter()
            try:
                candidates = self._reranker.rerank(
                    query,
                    rerank_candidates,
                    top_k=len(rerank_candidates),
                )
                reranker_applied = True
            except Exception as exc:  # noqa: BLE001 - RRF fallback is intentional
                candidates = fusion_candidates
                reranker_fallback_reason = str(exc) or exc.__class__.__name__
            rerank_ms = (perf_counter() - rerank_started) * 1000
        post_rerank_chunk_ids = [candidate.chunk.chunk_id for candidate in candidates]

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
        if use_small_to_big and callable(section_neighbors):
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
                "trace_id": request.trace_id,
                "dense_count": len(dense),
                "dense_incompatible_document_ids": dense_incompatible_document_ids,
                "sparse_count": len(sparse),
                "structural_count": len(structural),
                "dense_enabled": dense_enabled,
                "sparse_enabled": sparse_enabled,
                "structural_enabled": use_structural,
                "reranker_enabled": reranker_enabled and self._reranker is not None,
                "fusion_count": fusion_count,
                "final_count": len(candidates),
                "fusion_candidate_count": fusion_count,
                "rerank_candidate_count": len(rerank_input_chunk_ids),
                "final_candidate_count": len(candidates),
                "dense_chunk_ids": [item.chunk.chunk_id for item in dense],
                "sparse_chunk_ids": [item.chunk.chunk_id for item in sparse],
                "structural_chunk_ids": [item.chunk.chunk_id for item in structural],
                "pre_rerank_chunk_ids": pre_rerank_chunk_ids,
                "rerank_input_chunk_ids": rerank_input_chunk_ids,
                "post_rerank_chunk_ids": post_rerank_chunk_ids,
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
                "active_generation_count": (
                    len(active_generations) if active_generations is not None else None
                ),
                "small_to_big_enabled": use_small_to_big,
                "small_to_big_error": small_to_big_error,
                **small_to_big_metadata,
            },
        )

    def _resolve_active_generations(
        self,
        filters: VectorSearchFilter,
    ) -> Mapping[str, str | None] | None:
        if self._manifest is None:
            return None
        active = self._manifest.list_active_generations()
        if filters.document_ids:
            allowed_document_ids = set(filters.document_ids)
            active = {
                document_id: generation_id
                for document_id, generation_id in active.items()
                if document_id in allowed_document_ids
            }
        return active

    @staticmethod
    def _strategy(
        *,
        dense_error: str,
        sparse_error: str,
        structural: list[RetrievalCandidate],
        dense_enabled: bool = True,
        sparse_enabled: bool = True,
    ) -> str:
        if structural:
            if (not dense_enabled and not sparse_enabled) or (
                dense_error and sparse_error
            ):
                return "structural-only"
            return "hybrid+structural"
        if not dense_enabled:
            return "sparse-only"
        if not sparse_enabled:
            return "dense-only"
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
