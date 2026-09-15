from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVectorStoreConfig
from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import VectorSearchFilter, is_reference_chunk

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
        self._client = client or QdrantClient(
            path=str(Path(self._config.storage_path).expanduser().resolve())
        )

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
    ) -> None:
        if len(chunks) != len(vectors):
            raise RagVectorStoreError(
                f"chunk/vector count mismatch: {len(chunks)} chunks, {len(vectors)} vectors"
            )
        if not chunks:
            return
        self.ensure_collection()
        points = [
            qdrant_models.PointStruct(
                id=self._point_id(chunk.chunk_id),
                vector=self._validate_vector(vector),
                payload=self._chunk_payload(chunk),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
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
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise RagVectorStoreError("top_k must be positive")
        self.ensure_collection()
        query_vector = self._validate_vector(vector)
        try:
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=self._build_filter(filters),
                # Older indexes predate ``section_kind``. Fetch a bounded
                # surplus so the in-process legacy safeguard can still return
                # the requested number of non-reference candidates.
                limit=top_k * 3 if filters and filters.exclude_references else top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to search Qdrant collection") from exc

        candidates: list[RetrievalCandidate] = []
        for point in response.points:
            chunk = self._chunk_from_payload(point.payload)
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

    def delete_document(self, document_id: str) -> None:
        if not document_id:
            raise RagVectorStoreError("document_id must not be empty")
        self.ensure_collection()
        selector = qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="document_id",
                        match=qdrant_models.MatchValue(value=document_id),
                    )
                ]
            )
        )
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

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.ensure_collection()
        selector = qdrant_models.PointIdsList(
            points=[self._point_id(chunk_id) for chunk_id in chunk_ids]
        )
        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=selector,
                wait=True,
            )
        except Exception as exc:
            raise RagVectorStoreError("failed to delete stale Qdrant chunks") from exc

    def get_chunk(self, chunk_id: str) -> DocumentChunk | None:
        if not chunk_id:
            return None
        self.ensure_collection()
        try:
            records = self._client.retrieve(
                collection_name=self.collection_name,
                ids=[self._point_id(chunk_id)],
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RagVectorStoreError(f"failed to retrieve chunk: {chunk_id}") from exc
        if not records:
            return None
        chunk = self._chunk_from_payload(records[0].payload)
        return chunk if chunk.chunk_id == chunk_id else None

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
    def _point_id(chunk_id: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"aitrans-rag:{chunk_id}")

    @staticmethod
    def _chunk_payload(chunk: DocumentChunk) -> dict[str, Any]:
        payload = chunk.model_dump(mode="json")
        payload["source_kind"] = str(chunk.metadata.get("source_kind", ""))
        return payload

    @staticmethod
    def _chunk_from_payload(payload: dict[str, Any] | None) -> DocumentChunk:
        if not payload:
            raise RagVectorStoreError("Qdrant point is missing chunk payload")
        chunk_data = dict(payload)
        chunk_data.pop("source_kind", None)
        try:
            return DocumentChunk.model_validate(chunk_data)
        except Exception as exc:
            raise RagVectorStoreError(
                "Qdrant point contains invalid chunk payload"
            ) from exc

    @staticmethod
    def _build_filter(
        filters: VectorSearchFilter | None,
    ) -> qdrant_models.Filter | None:
        if filters is None:
            return None
        conditions: list[qdrant_models.FieldCondition] = []
        must_not: list[qdrant_models.FieldCondition] = []
        if filters.document_ids:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="document_id",
                    match=qdrant_models.MatchAny(any=filters.document_ids),
                )
            )
        if filters.source_kind:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="source_kind",
                    match=qdrant_models.MatchValue(value=filters.source_kind),
                )
            )
        if filters.language:
            conditions.append(
                qdrant_models.FieldCondition(
                    key="language",
                    match=qdrant_models.MatchValue(value=filters.language),
                )
            )
        for key, value in sorted(filters.metadata.items()):
            conditions.append(
                qdrant_models.FieldCondition(
                    key=f"metadata.{key}",
                    match=qdrant_models.MatchValue(value=value),
                )
            )
        if filters.exclude_references:
            must_not.append(
                qdrant_models.FieldCondition(
                    key="metadata.section_kind",
                    match=qdrant_models.MatchValue(value="references"),
                )
            )
        return (
            qdrant_models.Filter(must=conditions, must_not=must_not)
            if conditions or must_not
            else None
        )


__all__ = ["QdrantLocalVectorStore"]
