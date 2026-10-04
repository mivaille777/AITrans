from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVectorStoreConfig
from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import (
    VectorSearchFilter,
    effective_document_ids,
    is_reference_chunk,
)

_DISTANCES = {
    "cosine": qdrant_models.Distance.COSINE,
    "dot": qdrant_models.Distance.DOT,
    "euclid": qdrant_models.Distance.EUCLID,
    "manhattan": qdrant_models.Distance.MANHATTAN,
}


class QdrantLocalVectorStore:
    """Persistent Qdrant Local adapter for RAG document chunks."""

    def __init__(
        self,
        config: RagVectorStoreConfig | None = None,
        *,
        dimension: int = 1024,
        client: QdrantClient | None = None,
    ) -> None:
        self._config = config or RagVectorStoreConfig()
        if dimension <= 0:
            raise RagConfigurationError("vector dimension must be positive")
        if self._config.distance not in _DISTANCES:
            raise RagConfigurationError(
                f"unsupported vector distance: {self._config.distance!r}"
            )
        self._dimension = dimension
        self._owns_client = client is None
        self._client = client or self.create_client(self._config)

    @staticmethod
    def create_client(config: RagVectorStoreConfig) -> QdrantClient:
        if config.url:
            options = {"trust_env": False} if urlsplit(config.url).hostname in {
                "localhost", "127.0.0.1", "::1",
            } else {}
            return QdrantClient(url=config.url, timeout=config.timeout_seconds,
                api_key=os.environ.get("AITRANS_QDRANT_API_KEY") or None, **options)
        return QdrantClient(path=str(Path(config.storage_path).expanduser().resolve()))

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def collection_name(self) -> str:
        return self._config.collection_name

    def ensure_collection(self) -> None:
        expected_distance = _DISTANCES[self._config.distance]
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qdrant_models.VectorParams(
                    size=self.dimension,
                    distance=expected_distance,
                ),
            )
            return

        info = self._client.get_collection(self.collection_name)
        vector_params = info.config.params.vectors
        if not isinstance(vector_params, qdrant_models.VectorParams):
            raise RagConfigurationError(
                f"collection {self.collection_name!r} does not use a single dense vector"
            )
        if (
            vector_params.size != self.dimension
            or vector_params.distance != expected_distance
        ):
            raise RagConfigurationError(
                "existing Qdrant collection schema mismatch: "
                f"expected size={self.dimension}, distance={expected_distance.value}; "
                f"got size={vector_params.size}, distance={vector_params.distance.value}"
            )

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        generation_id: str | None = None,
    ) -> None:
        if len(chunks) != len(vectors):
            raise RagVectorStoreError(
                f"chunk/vector count mismatch: {len(chunks)} chunks, {len(vectors)} vectors"
            )
        if not chunks:
            return
        normalized_generation = self._normalize_generation_id(generation_id)
        chunk_generations = [self._chunk_generation(chunk) for chunk in chunks]
        if normalized_generation and any(
            chunk_generation and chunk_generation != normalized_generation
            for chunk_generation in chunk_generations
        ):
            raise RagVectorStoreError(
                "chunk generation metadata does not match generation_id"
            )
        self.ensure_collection()
        points = [
            qdrant_models.PointStruct(
                id=self._point_id(
                    chunk.chunk_id,
                    normalized_generation or chunk_generation,
                ),
                vector=self._validate_vector(vector),
                payload=self._chunk_payload(
                    chunk, normalized_generation or chunk_generation
                ),
            )
            for chunk, vector, chunk_generation in zip(
                chunks, vectors, chunk_generations, strict=True
            )
        ]
        try:
            self._client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to upsert chunks into Qdrant") from exc

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
        normalized_generation = self._normalize_generation_id(generation_id)
        effective_ids = effective_document_ids(
            filters,
            allowed_document_ids,
        )
        if effective_ids == []:
            return []
        scoped_document_ids = set(effective_ids) if effective_ids is not None else None
        if active_generations is not None:
            effective_active = {
                document_id: active_generation
                for document_id, active_generation in active_generations.items()
                if (scoped_document_ids is None or document_id in scoped_document_ids)
                and (
                    normalized_generation is None
                    or active_generation == normalized_generation
                )
            }
            if not effective_active:
                return []
        else:
            effective_active = None
        self.ensure_collection()
        query_vector = self._validate_vector(vector)
        try:
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=self._build_filter(
                    filters,
                    normalized_generation,
                    effective_active,
                    allowed_document_ids=allowed_document_ids,
                ),
                # Older indexes predate ``section_kind``. Fetch a bounded
                # surplus so the in-process legacy safeguard can still return
                # the requested number of non-reference candidates.
                limit=(top_k * 3 if filters and filters.exclude_references else top_k),
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to search Qdrant collection") from exc

        candidates: list[RetrievalCandidate] = []
        for point in response.points:
            payload = point.payload
            if not payload:
                continue
            payload_document_id = payload.get("document_id")
            if not isinstance(payload_document_id, str) or not payload_document_id:
                continue
            if (
                scoped_document_ids is not None
                and payload_document_id not in scoped_document_ids
            ):
                continue
            if not self._matches_payload_generation(
                payload,
                payload_document_id,
                normalized_generation,
                effective_active,
            ):
                continue
            chunk = self._chunk_from_payload(point.payload)
            if not self._matches_search_generation(
                point.payload,
                chunk,
                normalized_generation,
                effective_active,
            ):
                continue
            if filters and filters.exclude_references and is_reference_chunk(chunk):
                continue
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    dense_score=float(point.score),
                    rank=len(candidates) + 1,
                )
            )
            if len(candidates) >= top_k:
                break
        return candidates

    def delete_document(
        self,
        document_id: str,
        *,
        generation_id: str | None = None,
    ) -> None:
        if not document_id:
            raise RagVectorStoreError("document_id must not be empty")
        normalized_generation = self._normalize_generation_id(generation_id)
        self.ensure_collection()
        must = [
            qdrant_models.FieldCondition(
                key="document_id",
                match=qdrant_models.MatchValue(value=document_id),
            )
        ]
        if normalized_generation:
            must.append(self._generation_condition(normalized_generation))
        selector = qdrant_models.FilterSelector(filter=qdrant_models.Filter(must=must))
        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=selector,
                wait=True,
            )
        except Exception as exc:
            raise RagVectorStoreError(
                f"failed to delete Qdrant document: {document_id}"
            ) from exc

    def delete_chunks(
        self,
        chunk_ids: list[str],
        *,
        generation_id: str | None = None,
    ) -> None:
        if not chunk_ids:
            return
        normalized_generation = self._normalize_generation_id(generation_id)
        self.ensure_collection()
        selector = qdrant_models.PointIdsList(
            points=[
                self._point_id(chunk_id, normalized_generation)
                for chunk_id in chunk_ids
            ]
        )
        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=selector,
                wait=True,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to delete stale Qdrant chunks") from exc

    def get_chunk(
        self,
        chunk_id: str,
        *,
        generation_id: str | None = None,
    ) -> DocumentChunk | None:
        if not chunk_id:
            return None
        normalized_generation = self._normalize_generation_id(generation_id)
        self.ensure_collection()
        try:
            records = self._client.retrieve(
                collection_name=self.collection_name,
                ids=[self._point_id(chunk_id, normalized_generation)],
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError(f"failed to retrieve chunk: {chunk_id}") from exc
        if not records:
            return None
        chunk = self._chunk_from_payload(records[0].payload)
        return chunk if chunk.chunk_id == chunk_id else None

    def count_chunks(
        self,
        document_ids: list[str] | None = None,
        *,
        generation_id: str | None = None,
    ) -> int:
        """Count indexed chunks, optionally scoped to the supplied documents."""

        self.ensure_collection()
        normalized_generation = self._normalize_generation_id(generation_id)
        if document_ids is not None and not document_ids:
            return 0
        must: list[qdrant_models.FieldCondition] = []
        if document_ids:
            must.append(
                qdrant_models.FieldCondition(
                    key="document_id",
                    match=qdrant_models.MatchAny(any=document_ids),
                )
            )
        if normalized_generation:
            must.append(self._generation_condition(normalized_generation))
        count_filter = qdrant_models.Filter(must=must) if must else None
        try:
            result = self._client.count(
                collection_name=self.collection_name,
                count_filter=count_filter,
                exact=True,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to count Qdrant chunks") from exc
        return int(result.count)

    def list_chunks(
        self,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]:
        """List persisted chunks; an explicit ID limits the view to one generation."""

        normalized_generation = self._normalize_generation_id(generation_id)
        if not self._client.collection_exists(self.collection_name):
            return []
        scroll_filter = (
            qdrant_models.Filter(
                must=[self._generation_condition(normalized_generation)]
            )
            if normalized_generation
            else None
        )
        offset: Any = None
        chunks: list[DocumentChunk] = []
        try:
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=scroll_filter,
                    limit=512,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                chunks.extend(
                    self._chunk_from_payload(point.payload) for point in points
                )
                if offset is None:
                    break
        except Exception as exc:
            raise RagVectorStoreError("failed to list Qdrant chunks") from exc
        return sorted(
            chunks,
            key=lambda chunk: (
                chunk.document_id,
                self._chunk_generation(chunk) or "",
                chunk.page_number if chunk.page_number is not None else 10**9,
                chunk.chunk_index,
                chunk.chunk_id,
            ),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _validate_vector(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dimension:
            raise RagVectorStoreError(
                f"vector dimension mismatch: expected {self.dimension}, got {len(vector)}"
            )
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise RagVectorStoreError("vector contains a non-numeric value") from exc
        if not all(math.isfinite(value) for value in converted):
            raise RagVectorStoreError("vector contains non-finite values")
        return converted

    @staticmethod
    def _point_id(chunk_id: str, generation_id: str | None = None) -> UUID:
        if generation_id is None:
            identity = f"aitrans-rag:{chunk_id}"
        else:
            identity = f"aitrans-rag:g{len(generation_id)}:{generation_id}:{chunk_id}"
        return uuid5(NAMESPACE_URL, identity)

    @classmethod
    def _chunk_payload(
        cls,
        chunk: DocumentChunk,
        generation_id: str | None = None,
    ) -> dict[str, Any]:
        payload = chunk.model_dump(mode="json")
        payload["source_kind"] = str(chunk.metadata.get("source_kind", ""))
        chunk_generation = cls._chunk_generation(chunk)
        if generation_id and chunk_generation and generation_id != chunk_generation:
            raise RagVectorStoreError(
                "chunk generation metadata does not match generation_id"
            )
        effective_generation = generation_id or chunk_generation
        if effective_generation:
            payload["index_generation"] = effective_generation
            payload["metadata"] = {
                **payload.get("metadata", {}),
                "index_generation": effective_generation,
            }
        return payload

    @staticmethod
    def _chunk_from_payload(payload: dict[str, Any] | None) -> DocumentChunk:
        if not payload:
            raise RagVectorStoreError("Qdrant point is missing chunk payload")
        chunk_data = dict(payload)
        chunk_data.pop("source_kind", None)
        generation_id = str(chunk_data.pop("index_generation", "") or "").strip()
        if generation_id:
            metadata = dict(chunk_data.get("metadata") or {})
            metadata["index_generation"] = generation_id
            chunk_data["metadata"] = metadata
        try:
            return DocumentChunk.model_validate(chunk_data)
        except Exception as exc:
            raise RagVectorStoreError(
                "Qdrant point contains invalid chunk payload"
            ) from exc

    @staticmethod
    def _build_filter(
        filters: VectorSearchFilter | None,
        generation_id: str | None = None,
        active_generations: Mapping[str, str | None] | None = None,
        *,
        allowed_document_ids: list[str] | None = None,
    ) -> qdrant_models.Filter | None:
        conditions: list[qdrant_models.FieldCondition] = []
        must: list[Any] = conditions
        must_not: list[qdrant_models.FieldCondition] = []
        effective_ids = effective_document_ids(
            filters,
            allowed_document_ids,
        )
        if effective_ids is not None:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="document_id",
                    match=qdrant_models.MatchAny(any=effective_ids),
                )
            )
        if filters and filters.source_kind:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="source_kind",
                    match=qdrant_models.MatchValue(value=filters.source_kind),
                )
            )
        if filters and filters.language:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="language",
                    match=qdrant_models.MatchValue(value=filters.language),
                )
            )
        if filters:
            for key, value in sorted(filters.metadata.items()):
                conditions.append(
                    qdrant_models.FieldCondition(
                        key=f"metadata.{key}",
                        match=qdrant_models.MatchValue(value=value),
                    )
                )
        if filters and filters.exclude_references:
            must_not.append(
                qdrant_models.FieldCondition(
                    key="metadata.section_kind",
                    match=qdrant_models.MatchValue(value="references"),
                )
            )
        if active_generations is not None:
            scoped_generations = {
                document_id: active_generation
                for document_id, active_generation in active_generations.items()
                if effective_ids is None or document_id in effective_ids
            }
            generation_pairs = []
            for document_id, active_generation in sorted(scoped_generations.items()):
                pair_must: list[Any] = [
                    qdrant_models.FieldCondition(
                        key="document_id",
                        match=qdrant_models.MatchValue(value=document_id),
                    )
                ]
                if active_generation is None:
                    pair_must.append(
                        qdrant_models.IsEmptyCondition(
                            is_empty=qdrant_models.PayloadField(key="index_generation")
                        )
                    )
                else:
                    pair_must.append(
                        QdrantLocalVectorStore._generation_condition(active_generation)
                    )
                generation_pairs.append(qdrant_models.Filter(must=pair_must))
            if generation_pairs:
                must.append(qdrant_models.Filter(should=generation_pairs))
        elif generation_id is None:
            # Product calls without a generation keep their legacy view and
            # cannot accidentally see staged or retired generation points.
            must.append(
                qdrant_models.IsEmptyCondition(
                    is_empty=qdrant_models.PayloadField(key="index_generation")
                )
            )
        else:
            must.append(QdrantLocalVectorStore._generation_condition(generation_id))
        return qdrant_models.Filter(must=must, must_not=must_not)

    @staticmethod
    def _generation_condition(generation_id: str) -> qdrant_models.FieldCondition:
        return qdrant_models.FieldCondition(
            key="index_generation",
            match=qdrant_models.MatchValue(value=generation_id),
        )

    @classmethod
    def _matches_search_generation(
        cls,
        payload: dict[str, Any] | None,
        chunk: DocumentChunk,
        generation_id: str | None,
        active_generations: Mapping[str, str | None] | None,
    ) -> bool:
        if not cls._matches_payload_generation(
            payload,
            chunk.document_id,
            generation_id,
            active_generations,
        ):
            return False
        chunk_generation = cls._chunk_generation(chunk)
        if active_generations is not None:
            return chunk.document_id in active_generations and (
                chunk_generation == active_generations[chunk.document_id]
            )
        if generation_id is not None:
            return chunk_generation == generation_id
        return chunk_generation is None

    @staticmethod
    def _matches_payload_generation(
        payload: dict[str, Any] | None,
        document_id: str,
        generation_id: str | None,
        active_generations: Mapping[str, str | None] | None,
    ) -> bool:
        if not payload:
            return False
        raw_payload_generation = payload.get("index_generation")
        if raw_payload_generation is not None and not isinstance(
            raw_payload_generation, str
        ):
            return False
        payload_generation = str(raw_payload_generation or "").strip() or None
        metadata = payload.get("metadata") or {}
        raw_metadata_generation = (
            metadata.get("index_generation") if isinstance(metadata, Mapping) else None
        )
        if raw_metadata_generation is not None and not isinstance(
            raw_metadata_generation, str
        ):
            return False
        metadata_generation = str(raw_metadata_generation or "").strip() or None
        if (
            payload_generation is not None
            and metadata_generation is not None
            and payload_generation != metadata_generation
        ):
            return False
        if active_generations is not None:
            return document_id in active_generations and (
                payload_generation == active_generations[document_id]
            )
        if generation_id is not None:
            return payload_generation == generation_id
        return payload_generation is None and metadata_generation is None

    @staticmethod
    def _normalize_generation_id(generation_id: str | None) -> str | None:
        if generation_id is None:
            return None
        normalized = str(generation_id).strip()
        if not normalized:
            raise RagVectorStoreError("generation_id must not be empty")
        return normalized

    @staticmethod
    def _chunk_generation(chunk: DocumentChunk) -> str | None:
        generation = str(chunk.metadata.get("index_generation") or "").strip()
        return generation or None


__all__ = ["QdrantLocalVectorStore"]
