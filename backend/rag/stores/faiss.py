from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import numpy as np

from backend.rag.config import RagVectorStoreConfig
from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import (
    VectorSearchFilter,
    effective_document_ids,
    is_reference_chunk,
)
from backend.rag.stores.faiss_runtime import make_index
from backend.rag.stores.local_repository import (
    LocalVectorRepository,
    generation_key,
    normalize_rows,
    vector_array,
)


def matches_chunk(
    chunk: DocumentChunk,
    filters: VectorSearchFilter | None,
    allowed_ids: list[str] | None,
    generation: str,
    active_generations: Mapping[str, str | None] | None,
    generation_id: str | None = None,
) -> bool:
    if allowed_ids is not None and chunk.document_id not in allowed_ids:
        return False
    if active_generations is not None:
        if chunk.document_id not in active_generations or generation != generation_key(
            active_generations[chunk.document_id]
        ):
            return False
        if generation_id is not None and generation != generation_id:
            return False
    elif generation != (generation_id or ""):
        return False
    if filters is None:
        return True
    if filters.language and filters.language != chunk.language:
        return False
    if filters.source_kind and filters.source_kind != chunk.metadata.get("source_kind"):
        return False
    for key, expected in filters.metadata.items():
        actual: Any = chunk.metadata
        for part in key.split("."):
            actual = actual.get(part) if isinstance(actual, dict) else None
        if type(actual) is not type(expected) or actual != expected:
            return False
    return not (filters.exclude_references and is_reference_chunk(chunk))


def ranked_search(index, query: np.ndarray, rows, top_k: int, distance: str):
    if not rows:
        return []
    count = min(top_k + 1, len(rows))
    scores, ids = index.search(query.reshape(1, -1), count)
    # Include all boundary ties before applying the deterministic domain ordering.
    if count > top_k and scores[0, top_k] == scores[0, top_k - 1]:
        scores, ids = index.search(query.reshape(1, -1), len(rows))
    by_id = {row.vector_id: row for row in rows}
    result = [
        (by_id[int(item_id)], float(score))
        for item_id, score in zip(ids[0], scores[0])
        if int(item_id) in by_id
    ]
    reverse = distance in {"cosine", "dot"}
    result.sort(
        key=lambda pair: (
            (-pair[1] if reverse else pair[1]),
            pair[0].chunk.document_id,
            pair[0].chunk.chunk_id,
            pair[0].generation,
        )
    )
    if distance == "euclid":
        result = [(row, float(np.sqrt(max(0.0, score)))) for row, score in result]
    return result[:top_k]


class FaissVectorStore:
    def __init__(
        self,
        config: RagVectorStoreConfig | None = None,
        *,
        dimension: int = 1024,
        repository: LocalVectorRepository | None = None,
        fingerprint: dict | str | None = None,
    ) -> None:
        self._config = config or RagVectorStoreConfig()
        if dimension <= 0 or self._config.distance not in {
            "cosine",
            "dot",
            "euclid",
            "manhattan",
        }:
            raise RagConfigurationError("invalid vector dimension or distance")
        self._dimension = dimension
        self._owns_repository = repository is None
        self.repository = repository or LocalVectorRepository(self._config.storage_path)
        self._fingerprint = (
            json.dumps(fingerprint, sort_keys=True)
            if isinstance(fingerprint, dict)
            else (fingerprint or "")
        )
        self._cache_revision = -1
        self._index = None
        self._rows = []
        self.execution_info = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def collection_name(self) -> str:
        return self._config.collection_name

    def ensure_collection(self) -> None:
        self.repository.ensure_collection(
            self.collection_name,
            "text",
            self.dimension,
            self._config.distance,
            self._fingerprint,
        )

    def bind_fingerprint(self, fingerprint: dict) -> None:
        value = json.dumps(fingerprint, sort_keys=True)
        self.repository.ensure_collection(
            self.collection_name, "text", self.dimension, self._config.distance, value
        )
        self._fingerprint = value

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        generation_id: str | None = None,
    ) -> None:
        if len(chunks) != len(vectors):
            raise RagVectorStoreError("chunk/vector count mismatch")
        key = generation_key(generation_id)
        values = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            existing = generation_key(
                chunk.metadata.get("index_generation"), allow_empty=True
            )
            if key and existing and existing != key:
                raise RagVectorStoreError(
                    "chunk generation metadata does not match generation_id"
                )
            actual_key = key or existing
            metadata = dict(chunk.metadata)
            if actual_key:
                metadata["index_generation"] = actual_key
            prepared = chunk.model_copy(update={"metadata": metadata}, deep=True)
            array = vector_array(vector, self.dimension)
            if self._config.distance == "cosine":
                array = normalize_rows(array)
            values.append((prepared, array, "", None))
        if values:
            self.ensure_collection()
            self.repository.write(self.collection_name, values)

    def _snapshot(self):
        schema = self.repository.collection(self.collection_name)
        if schema is None:
            return []
        if self._cache_revision != schema["revision"]:
            rows = self.repository.rows(self.collection_name, with_vectors=True)
            matrix = np.asarray([row.vector for row in rows], dtype=np.float32).reshape(
                -1, self.dimension
            )
            index = make_index(
                matrix,
                np.array([row.vector_id for row in rows], dtype=np.int64),
                self._config.distance,
            )
            self._rows, self._index, self._cache_revision = (
                rows,
                index,
                schema["revision"],
            )
        return self._rows

    def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
        allowed_document_ids: list[str] | None = None,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise RagVectorStoreError("top_k must be positive")
        key = generation_key(generation_id) if generation_id is not None else None
        allowed = effective_document_ids(filters, allowed_document_ids)
        if allowed == [] or active_generations == {}:
            return []
        query = vector_array(vector, self.dimension)
        if self._config.distance == "cosine":
            query = normalize_rows(query)
        self.ensure_collection()
        try:
            with self.repository.lock:
                all_rows = self._snapshot()
                rows = [
                    row
                    for row in all_rows
                    if matches_chunk(
                        row.chunk,
                        filters,
                        allowed,
                        row.generation,
                        active_generations,
                        key,
                    )
                ]
                if not rows:
                    return []
                index = (
                    self._index
                    if len(rows) == len(all_rows)
                    else make_index(
                        np.array([row.vector for row in rows]),
                        np.array([row.vector_id for row in rows]),
                        self._config.distance,
                    )
                )
                ranked = ranked_search(index, query, rows, top_k, self._config.distance)
                self.execution_info = index.diagnostics()
                return [
                    RetrievalCandidate(
                        chunk=row.chunk.model_copy(deep=True),
                        dense_score=score,
                        rank=rank,
                    )
                    for rank, (row, score) in enumerate(ranked, 1)
                ]
        except RagVectorStoreError:
            raise
        except Exception as exc:
            raise RagVectorStoreError("failed to search FAISS collection") from exc

    def list_chunks(self, *, generation_id: str | None = None) -> list[DocumentChunk]:
        key = generation_key(generation_id) if generation_id is not None else None
        rows = self.repository.rows(self.collection_name, generation=key)
        return sorted(
            [row.chunk for row in rows if key is None or row.generation == key],
            key=lambda c: (
                c.document_id,
                str(c.metadata.get("index_generation") or ""),
                c.page_number if c.page_number is not None else 10**9,
                c.chunk_index,
                c.chunk_id,
            ),
        )

    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None
    ) -> DocumentChunk | None:
        key = generation_key(generation_id)
        return next(
            (
                row.chunk
                for row in self.repository.rows(self.collection_name, chunk_id=chunk_id, generation=key)
                if row.chunk.chunk_id == chunk_id and row.generation == key
            ),
            None,
        )

    def count_chunks(
        self, document_ids: list[str] | None = None, *, generation_id: str | None = None
    ) -> int:
        key = generation_key(generation_id) if generation_id is not None else None
        return self.repository.count(self.collection_name, document_ids=document_ids, generation=key)

    def delete_document(
        self, document_id: str, *, generation_id: str | None = None
    ) -> None:
        if not document_id:
            raise RagVectorStoreError("document_id must not be empty")
        self.ensure_collection()
        self.repository.delete(
            self.collection_name,
            document_id=document_id,
            generation=generation_key(generation_id)
            if generation_id is not None
            else None,
        )

    def delete_chunks(
        self, chunk_ids: list[str], *, generation_id: str | None = None
    ) -> None:
        if chunk_ids:
            self.ensure_collection()
            self.repository.delete(
                self.collection_name,
                chunk_ids=chunk_ids,
                generation=generation_key(generation_id),
            )

    def close(self) -> None:
        self._index = None
        self._rows = []
        if self._owns_repository:
            self.repository.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
