from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.rag.cache import EmbeddingCache, cache_key
from backend.rag.config import RagRetrievalConfig
from backend.rag.embeddings.base import (
    EmbeddingFingerprint,
    EmbeddingProvider,
    embedding_fingerprint,
)
from backend.rag.exceptions import RagRetrievalError
from backend.rag.fusion import rrf_fuse
from backend.rag.index_manifest import IndexManifest
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.rerankers.base import RerankerProvider
from backend.rag.retrievers.base import RetrievalRequest, record_channel_hits
from backend.rag.retrievers.bm25 import BM25Retriever
from backend.rag.retrievers.vector import VectorRetriever
from backend.rag.small_to_big import SmallToBigContextExpander
from backend.rag.sparse.store import SparseRetriever
from backend.rag.stores.base import VectorSearchFilter, VectorStore
from backend.rag.structure_retrieval import order_structural_candidates

if TYPE_CHECKING:
    from backend.rag.graph_retriever import GraphRetriever


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
        graph_retriever: GraphRetriever | None = None,
    ) -> None:
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._sparse = sparse_retriever
        self._config = config or RagRetrievalConfig()
        self._reranker = reranker
        self._manifest = manifest
        self._graph_retriever = graph_retriever
        self._embedding_cache = EmbeddingCache(self._config.embedding_cache_size) if self._config.embedding_cache_size else None

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
        graph_enabled: bool | None = None,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        if not query or not query.strip():
            raise RagRetrievalError("retrieval query must not be empty")
        desired_top_k = final_top_k or self._config.final_top_k
        if desired_top_k <= 0:
            raise ValueError("final_top_k must be positive")

        started = perf_counter()
        started_at = datetime.now(UTC)
        stage_timings: dict[str, dict] = {}
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
            **({"trace_id": trace_id} if trace_id else {}),
        )
        retrieval_span_id = f"{request.trace_id}:retrieve:{uuid4().hex[:12]}"
        effective_filters = request.search_filters()

        dense: list[RetrievalCandidate] = []
        sparse: list[RetrievalCandidate] = []
        structural: list[RetrievalCandidate] = []
        graph: list[RetrievalCandidate] = []
        graph_trace: dict = {}
        use_graph = (
            self._graph_retriever is not None
            if graph_enabled is None
            else graph_enabled
        )
        use_structural = structural_enabled and bool(section_hints)
        use_small_to_big = (
            self._config.small_to_big_enabled
            if small_to_big_enabled is None
            else small_to_big_enabled
        )
        if (
            not dense_enabled
            and not sparse_enabled
            and not use_structural
            and not use_graph
        ):
            raise ValueError("at least one retrieval channel must be enabled")
        dense_error = ""
        sparse_error = ""
        structural_error = ""
        graph_error = ""
        graph_ms = 0.0
        embedding_ms = 0.0
        dense_ms = 0.0
        sparse_ms = 0.0
        dense_incompatible_document_ids: list[str] = []
        embedding_cache_hit = False
        embedding_started = dense_started = None

        def stamp_stage(name: str, stage_started: float, error: str = "") -> None:
            ended = perf_counter()
            stage_timings[name] = {
                "trace_id": request.trace_id, "span_id": f"{retrieval_span_id}:{name}",
                "parent_id": retrieval_span_id, "stage": name,
                "started_at": (started_at + timedelta(seconds=stage_started - started)).isoformat(),
                "ended_at": (started_at + timedelta(seconds=ended - started)).isoformat(),
                "elapsed_ms": (ended - stage_started) * 1000,
                "status": "error" if error else "complete", "error": error,
            }

        def check_deadline(channel_started: float) -> None:
            if self._config.channel_deadline_ms is not None and (perf_counter() - channel_started) * 1000 > self._config.channel_deadline_ms:
                raise TimeoutError("retrieval channel deadline exceeded")

        if dense_enabled:
            try:
                embedding_started = perf_counter()
                fingerprint = getattr(self._embedding, "fingerprint", None)
                key = cache_key(query=query, scope=request.allowed_document_ids, generations=active_generations,
                                model=fingerprint.as_dict(), query_version="embedding-query-v1") if self._embedding_cache is not None and isinstance(fingerprint, EmbeddingFingerprint) else None
                cached = self._embedding_cache.get(key) if key is not None else None
                embedding_cache_hit = cached is not None
                vector = list(cached) if cached is not None else self._embedding.embed_query(query)
                check_deadline(embedding_started)
                if key is not None and cached is None:
                    self._embedding_cache.put(key, vector)
                embedding_ms = (perf_counter() - embedding_started) * 1000
                stamp_stage("embedding", embedding_started)
                if not embedding_cache_hit:
                    stage_timings["embedding"].update(getattr(self._embedding, "last_call_timings", {}))
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
                check_deadline(dense_started)
                dense_ms = (perf_counter() - dense_started) * 1000
            except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
                dense = []
                dense_error = str(exc) or exc.__class__.__name__
            if embedding_started is not None and "embedding" not in stage_timings:
                stamp_stage("embedding", embedding_started, dense_error)
            if dense_started is not None:
                stamp_stage("dense", dense_started, dense_error)

        if sparse_enabled:
            sparse_started = perf_counter()
            try:
                sparse = BM25Retriever(self._sparse).retrieve(
                    replace(request, top_k=self._config.sparse_top_k)
                )
                check_deadline(sparse_started)
            except Exception as exc:  # noqa: BLE001 - intentional degraded retrieval
                sparse = []
                sparse_error = str(exc) or exc.__class__.__name__
            sparse_ms = (perf_counter() - sparse_started) * 1000
            stamp_stage("sparse", sparse_started, sparse_error)

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
                check_deadline(structural_started)
            except Exception as exc:  # noqa: BLE001 - structural recall is additive
                structural = []
                structural_error = str(exc) or exc.__class__.__name__
            structural_ms = (perf_counter() - structural_started) * 1000
            stamp_stage("structural", structural_started, structural_error)

        if use_graph:
            graph_started = perf_counter()
            try:
                if self._graph_retriever is None:
                    raise RagRetrievalError("graph channel is not configured")
                graph_result = self._graph_retriever.retrieve_with_trace(
                    replace(request, top_k=self._config.fusion_top_k)
                )
                graph, graph_trace = graph_result.candidates, graph_result.metadata
                check_deadline(graph_started)
                if graph_trace.get("reason") == "deadline_exceeded":
                    graph_error = "graph query deadline exceeded"
            except Exception as exc:  # noqa: BLE001 - graph is an optional channel
                graph = []
                graph_error = str(exc) or exc.__class__.__name__
            graph_ms = (perf_counter() - graph_started) * 1000
            stamp_stage("graph", graph_started, graph_error)

        if (
            (dense_error or sparse_error or structural_error or graph_error)
            and (not dense_enabled or dense_error)
            and (not sparse_enabled or sparse_error)
            and (not use_graph or graph_error)
            and not structural
        ):
            raise RagRetrievalError(
                "all enabled retrieval channels failed (dense and sparse): "
                f"dense={dense_error}; sparse={sparse_error}; structural={structural_error}"
                + (f"; graph={graph_error}" if use_graph else "")
            )
        fusion_started = perf_counter()
        candidates = rrf_fuse(
            [ranked for ranked in (dense, sparse, structural, graph) if ranked],
            limit=max(self._config.fusion_top_k, desired_top_k),
        )
        fusion_ms = (perf_counter() - fusion_started) * 1000
        stamp_stage("fusion", fusion_started)
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
            item
            for item in (dense_error, sparse_error, structural_error, graph_error)
            if item
        )
        if graph:
            strategy = (
                "graph-only"
                if not (dense or sparse or structural)
                else strategy + "+graph"
            )
        elif use_graph and not (dense_enabled or sparse_enabled or use_structural):
            strategy = "graph-only"
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
                check_deadline(rerank_started)
                reranker_applied = True
            except Exception as exc:  # noqa: BLE001 - RRF fallback is intentional
                candidates = fusion_candidates
                reranker_fallback_reason = str(exc) or exc.__class__.__name__
            rerank_ms = (perf_counter() - rerank_started) * 1000
            stamp_stage("rerank", rerank_started, reranker_fallback_reason)
            stage_timings["rerank"].update(getattr(self._reranker, "last_call_timings", {}))
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
                "retrieval_span": {"trace_id": request.trace_id, "span_id": retrieval_span_id,
                    "parent_id": request.trace_id, "stage": "retrieval",
                    "started_at": started_at.isoformat(),
                    "ended_at": (started_at + timedelta(seconds=perf_counter() - started)).isoformat()},
                "allowed_document_ids": list(request.allowed_document_ids) if request.allowed_document_ids is not None else None,
                "active_generations": dict(active_generations) if active_generations is not None else None,
                "stage_timings": stage_timings,
                "dense_count": len(dense),
                "dense_incompatible_document_ids": dense_incompatible_document_ids,
                "sparse_count": len(sparse),
                "structural_count": len(structural),
                "graph_count": len(graph),
                "graph_hits": len(graph),
                "graph_enabled": use_graph,
                "graph_trace": graph_trace,
                "graph_error": graph_error,
                "graph_search_ms": graph_ms,
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
                "embedding_cache_hit": embedding_cache_hit,
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

    def validate_evidence_candidates(
        self, result: RetrievalResult, *, filters: VectorSearchFilter | None = None,
    ) -> None:
        """Recheck trusted scope and current publication before creating citations."""
        request = RetrievalRequest(
            query=result.query, top_k=max(1, len(result.candidates)),
            filters=filters or VectorSearchFilter(),
            active_generations=self._resolve_active_generations(filters or VectorSearchFilter()),
        )
        valid = record_channel_hits(request, result.candidates, channel="evidence", score_field="fusion_score")
        if len(valid) != len(result.candidates):
            raise RagRetrievalError("evidence is outside the current scope or active generation")
        getter = getattr(self._vector_store, "get_chunk", None)
        if self._manifest is not None and callable(getter):
            for candidate in result.candidates:
                chunk = candidate.chunk
                generation = (request.active_generations or {}).get(chunk.document_id)
                stored = getter(chunk.chunk_id, generation_id=generation)
                if stored is None or stored.document_id != chunk.document_id:
                    raise RagRetrievalError("evidence source chunk is missing from the active index")
                if (
                    chunk.document_hash != stored.document_hash
                    or chunk.source_uri != stored.source_uri
                    or chunk.page_number != stored.page_number
                ):
                    raise RagRetrievalError("evidence source locator does not match the active index")
                span = chunk.source_span
                original = stored.source_span
                if span is None:
                    start = chunk.start_char - stored.start_char
                    end = chunk.end_char - stored.start_char
                    exact = (
                        chunk.text == stored.text and chunk.start_char == stored.start_char
                        and chunk.end_char == stored.end_char
                    )
                    excerpt = 0 <= start < end <= len(stored.text) and stored.text[start:end] == chunk.text
                    if original is not None or not (exact or excerpt):
                        raise RagRetrievalError("evidence source content does not match the active index")
                if span is not None and (
                    original is None or span.document_hash != original.document_hash
                    or span.document_text_hash != original.document_text_hash
                    or span.start_char != chunk.start_char or span.end_char != chunk.end_char
                    or span.source_uri != original.source_uri
                    or span.page_start != original.page_start or span.page_end != original.page_end
                    or span.quote_hash != sha256(chunk.text.encode("utf-8")).hexdigest()
                    or span.start_char < original.start_char or span.end_char > original.end_char
                    or stored.text[span.start_char - original.start_char:span.end_char - original.start_char] != chunk.text
                ):
                    raise RagRetrievalError("evidence source span does not match the active index")
        if self._resolve_active_generations(request.filters) != request.active_generations:
            raise RagRetrievalError("evidence active generation changed during source validation")

    def get_active_chunk(
        self, chunk_id: str, *, filters: VectorSearchFilter | None = None,
    ) -> DocumentChunk | None:
        """Resolve JIT reads through the same publication and scope snapshot as search."""
        request = RetrievalRequest(
            query=f"read:{chunk_id}", top_k=1, filters=filters or VectorSearchFilter(),
            active_generations=self._resolve_active_generations(filters or VectorSearchFilter()),
        )
        getter = getattr(self._sparse, "get_chunk", None)
        if not callable(getter):
            getter = self._vector_store.get_chunk
        generations = (
            dict.fromkeys(request.active_generations.values())
            if request.active_generations is not None else [None]
        )
        for generation in generations:
            chunk = getter(chunk_id, generation_id=generation)
            if chunk is not None and record_channel_hits(
                request, [RetrievalCandidate(chunk=chunk)], channel="jit-read", score_field="fusion_score",
            ):
                return chunk
        return None

    def evidence_cache_version(self, *, filters: VectorSearchFilter | None = None) -> str | None:
        """Version document evidence against the current published index and retrieval settings."""
        effective_filters = filters or VectorSearchFilter()
        active = self._resolve_active_generations(effective_filters)
        if active is None:
            return None
        versions = {}
        for document_id, generation in active.items():
            record = self._manifest.get(document_id)
            versions[document_id] = [generation, record.content_hash if record is not None else ""]
        return cache_key(
            query="", scope=effective_filters.document_ids, generations=versions,
            model={
                "embedding": embedding_fingerprint(self._embedding).as_dict(),
                "retrieval": self._config.model_dump(mode="json"),
                "reranker": id(self._reranker) if self._reranker is not None else None,
                "graph_retriever": id(self._graph_retriever) if self._graph_retriever is not None else None,
            },
            query_version="scoped-evidence-v1",
        )

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
