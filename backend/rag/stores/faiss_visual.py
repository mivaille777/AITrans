from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter

import numpy as np

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.exceptions import RagVectorStoreError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import VectorSearchFilter, effective_document_ids
from backend.rag.stores.faiss import make_index, matches_chunk, ranked_search
from backend.rag.stores.local_repository import (
    LocalVectorRepository,
    generation_key,
    vector_array,
)
from backend.rag.visual_scoring import maxsim, pool_multivector


class FaissVisualMultiVectorStore:
    """FAISS centroid recall followed by local exact MaxSim on durable tokens."""

    def __init__(
        self,
        config: RagVisualRetrievalConfig,
        *,
        repository: LocalVectorRepository | None = None,
        policy=None,
    ) -> None:
        from backend.rag.visual_adaptive import AdaptivePrefetchPolicy
        from backend.rag.visual_retrieval import visual_retrieval_index_version

        self._config = config.model_copy(deep=True)
        self._version = visual_retrieval_index_version(config)
        self._owns_repository = repository is None
        self.repository = repository or LocalVectorRepository(config.storage_path)
        self._prefetch_policy = policy or AdaptivePrefetchPolicy.from_environment()
        self._cache_revision = -1
        self._rows = []
        self._index = None
        self.execution_info = {}

    @property
    def collection_name(self) -> str:
        return self._config.collection_name

    @property
    def dimension(self) -> int:
        return self._config.dimension

    @property
    def prefetch_policy(self):
        return self._prefetch_policy

    def ensure_collection(self) -> None:
        self.repository.ensure_collection(
            self.collection_name,
            "visual",
            self.dimension,
            self._config.distance,
            self._version,
        )

    def has_document(
        self,
        document_id: str,
        *,
        index_version: str,
        generation_id: str | None = None,
        content_hash: str | None = None,
    ) -> bool:
        return any(
            row.chunk.document_id == document_id
            and row.index_version == index_version
            and (
                generation_id is None
                or row.generation == generation_key(generation_id, allow_empty=True)
            )
            and (content_hash is None or row.chunk.document_hash == content_hash)
            for row in self.repository.rows(self.collection_name)
        )

    def replace_document(
        self,
        document_id: str,
        chunks: list[DocumentChunk],
        vectors: list[list[list[float]]],
        *,
        index_version: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise RagVectorStoreError("visual chunk/vector count mismatch")
        if not chunks:
            self.delete_document(document_id)
            return
        generations = {
            generation_key(c.metadata.get("index_generation"), allow_empty=True)
            for c in chunks
        }
        if len(generations) != 1 or any(c.document_id != document_id for c in chunks):
            raise RagVectorStoreError(
                "visual replacement must contain one document and generation"
            )
        if (
            len({c.chunk_id for c in chunks}) != len(chunks)
            or index_version != self._version
        ):
            raise RagVectorStoreError(
                "duplicate visual chunk IDs or visual index version mismatch"
            )
        values = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            array = vector_array(vector, self.dimension, multivector=True)
            coarse = None
            try:
                coarse = vector_array(
                    pool_multivector(array, self.dimension), self.dimension
                )
            except RagVectorStoreError:
                if self._config.prefetch_enabled:
                    raise
            prepared = chunk.model_copy(
                update={
                    "metadata": {
                        **chunk.metadata,
                        "visual_index_version": index_version,
                    }
                },
                deep=True,
            )
            values.append((prepared, array, index_version, coarse))
        self.ensure_collection()
        self.repository.write(
            self.collection_name,
            values,
            replace=(document_id, generations.pop(), index_version),
        )

    def _selected(self, filters, active_generations):
        schema = self.repository.collection(self.collection_name)
        if schema is None:
            return []
        if self._cache_revision != schema["revision"]:
            rows = [
                row
                for row in self.repository.rows(self.collection_name, with_coarse=True)
                if row.index_version == self._version
            ]
            index = None
            if rows and all(row.coarse is not None for row in rows):
                index = make_index(
                    np.array([row.coarse for row in rows]),
                    np.array([row.vector_id for row in rows]),
                    "dot",
                )
            self._rows, self._index, self._cache_revision = (
                rows,
                index,
                schema["revision"],
            )
        allowed = effective_document_ids(filters, None)
        return [
            row
            for row in self._rows
            if matches_chunk(
                row.chunk, filters, allowed, row.generation, active_generations
            )
        ]

    def estimate_candidate_count(self, filters=None, *, active_generations=None) -> int:
        with self.repository.lock:
            return len(self._selected(filters, active_generations))

    def _coarse_candidates(self, rows, query, prefetch_k):
        if any(row.coarse is None for row in rows):
            raise RagVectorStoreError(
                "visual coarse vector is missing; rebuild the visual index"
            )
        index = self._index
        if len(rows) != len(self._rows) or index is None:
            matrix = np.array([row.coarse for row in rows], dtype=np.float32)
            index = make_index(matrix, np.array([row.vector_id for row in rows]), "dot")
        ranked = ranked_search(
            index,
            vector_array(pool_multivector(query, self.dimension), self.dimension),
            rows,
            prefetch_k,
            "dot",
        )
        self.execution_info = index.diagnostics()
        return [
            row
            for row, _ in ranked
        ]

    def _score(
        self,
        rows,
        query,
        top_k,
        *,
        mode: str,
        total: int,
        prefetch_k: int,
        adaptive: bool,
        fallback: str = "",
        started: float,
    ):
        scores = []
        selected_by_id = {row.vector_id: row for row in rows}
        ids = list(selected_by_id)
        for start in range(0, len(ids), 32):
            pages = self.repository.rows(
                self.collection_name,
                with_vectors=True,
                vector_ids=ids[start : start + 32],
            )
            for page in pages:
                score = maxsim(query, page.vector, distance=self._config.distance)
                scores.append((selected_by_id[page.vector_id], score))
        scores.sort(
            key=lambda pair: (
                -pair[1],
                pair[0].chunk.document_id,
                pair[0].chunk.chunk_id,
                pair[0].generation,
            )
        )
        return [
            RetrievalCandidate(
                chunk=row.chunk.model_copy(deep=True),
                rank=rank,
                metadata={
                    "retrieval_channel": "visual",
                    "visual_score": score,
                    "visual_search_mode": mode,
                    "visual_prefetch_limit": prefetch_k,
                    "visual_prefetch_k": min(prefetch_k, total),
                    "visual_candidate_count": total,
                    "visual_prefetch_adaptive": adaptive,
                    "visual_prefetch_fallback_reason": fallback,
                    "visual_maxsim_candidate_reduction": 0.0
                    if mode.startswith("full-maxsim")
                    else max(0.0, 1.0 - len(rows) / total),
                    "visual_store_search_ms": (perf_counter() - started) * 1000,
                },
            )
            for rank, (row, score) in enumerate(scores[:top_k], 1)
        ]

    def search(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]:
        from backend.rag.visual_adaptive import adaptive_prefetch_top_k

        if top_k <= 0:
            raise RagVectorStoreError("visual top_k must be positive")
        if active_generations == {}:
            return []
        matrix = vector_array(query, self.dimension, multivector=True)
        started = perf_counter()
        self.ensure_collection()
        with self.repository.lock:
            rows = self._selected(filters, active_generations)
            if not rows:
                return []
            if not self._config.prefetch_enabled:
                return self._score(
                    rows,
                    matrix,
                    top_k,
                    mode="full-maxsim",
                    total=len(rows),
                    prefetch_k=len(rows),
                    adaptive=False,
                    started=started,
                )
            k = adaptive_prefetch_top_k(
                candidate_count=len(rows),
                visual_top_k=top_k,
                fallback_prefetch_k=max(top_k, self._config.prefetch_top_k),
                policy=self._prefetch_policy,
            )
            try:
                candidates = self._coarse_candidates(rows, matrix, k)
            except Exception as exc:
                if not self._config.prefetch_fallback_to_full_scan:
                    raise RagVectorStoreError(
                        "failed to run visual FAISS prefetch"
                    ) from exc
                return self._score(
                    rows,
                    matrix,
                    top_k,
                    mode="full-maxsim-fallback",
                    total=len(rows),
                    prefetch_k=k,
                    adaptive=self._prefetch_policy.enabled,
                    fallback=str(exc),
                    started=started,
                )
            mode = (
                "faiss-adaptive-coarse-maxsim"
                if self._prefetch_policy.enabled
                else "faiss-coarse-maxsim"
            )
            return self._score(
                candidates,
                matrix,
                top_k,
                mode=mode,
                total=len(rows),
                prefetch_k=k,
                adaptive=self._prefetch_policy.enabled,
                started=started,
            )

    def search_full_maxsim(
        self, query, *, top_k: int, filters=None, active_generations=None
    ):
        if top_k <= 0:
            raise RagVectorStoreError("visual top_k must be positive")
        started = perf_counter()
        matrix = vector_array(query, self.dimension, multivector=True)
        with self.repository.lock:
            rows = self._selected(filters, active_generations)
            return (
                self._score(
                    rows,
                    matrix,
                    top_k,
                    mode="full-maxsim-oracle",
                    total=len(rows),
                    prefetch_k=len(rows),
                    adaptive=False,
                    started=started,
                )
                if rows
                else []
            )

    def fixed_prefetch_store(self, prefetch_k: int):
        from backend.rag.visual_adaptive import AdaptivePrefetchPolicy

        if prefetch_k <= 0:
            raise ValueError("prefetch_k must be positive")
        config = self._config.model_copy(
            update={"prefetch_top_k": max(prefetch_k, self._config.visual_top_k)}
        )
        return FaissVisualMultiVectorStore(
            config,
            repository=self.repository,
            policy=AdaptivePrefetchPolicy(
                enabled=False,
                min_k=self._prefetch_policy.min_k,
                max_k=self._prefetch_policy.max_k,
                candidate_ratio=self._prefetch_policy.candidate_ratio,
            ),
        )

    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None
    ) -> DocumentChunk | None:
        key = generation_key(generation_id)
        return next(
            (
                row.chunk
                for row in self.repository.rows(self.collection_name)
                if row.chunk.chunk_id == chunk_id
                and row.generation == key
                and row.index_version == self._version
            ),
            None,
        )

    def list_chunks(self) -> list[DocumentChunk]:
        return [row.chunk for row in self.repository.rows(self.collection_name)]

    def delete_document(self, document_id: str) -> None:
        if document_id:
            self.repository.delete(self.collection_name, document_id=document_id)

    def close(self) -> None:
        self._index = None
        self._rows = []
        if self._owns_repository:
            self.repository.close()
