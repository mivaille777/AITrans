from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.visual_retrieval import QdrantVisualMultiVectorStore

COARSE_VECTOR_NAME = "coarse"
LATE_VECTOR_NAME = "late"
TWO_STAGE_VISUAL_SCHEMA_VERSION = "visual-prefetch-v1"

_DISTANCE = {
    "cosine": qdrant_models.Distance.COSINE,
    "dot": qdrant_models.Distance.DOT,
}


class QdrantTwoStageVisualStore(QdrantVisualMultiVectorStore):
    """Two-stage visual store: centroid prefetch followed by MaxSim reranking.

    Each visual item keeps the original ColQwen/ColPali token multivector for
    late interaction and an L2-normalized centroid derived from the same token
    rows. The centroid is intentionally recall-oriented and only narrows the
    candidate set; the final score always comes from MaxSim.
    """

    @property
    def collection_name(self) -> str:
        return (
            f"{self._config.collection_name}_2stage_"
            f"mv{self.dimension}_{self._config.distance}"
        )

    def ensure_collection(self) -> None:
        distance = _DISTANCE[self._config.distance]
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    COARSE_VECTOR_NAME: qdrant_models.VectorParams(
                        size=self.dimension,
                        distance=distance,
                        on_disk=self._config.on_disk,
                    ),
                    LATE_VECTOR_NAME: qdrant_models.VectorParams(
                        size=self.dimension,
                        distance=distance,
                        multivector_config=qdrant_models.MultiVectorConfig(
                            comparator=qdrant_models.MultiVectorComparator.MAX_SIM,
                        ),
                        hnsw_config=qdrant_models.HnswConfigDiff(m=0),
                        on_disk=self._config.on_disk,
                    ),
                },
            )
            return

        info = self._client.get_collection(self.collection_name)
        params = info.config.params.vectors
        if not isinstance(params, dict):
            raise RagConfigurationError(
                f"two-stage visual collection {self.collection_name!r} "
                "must use named vectors"
            )
        coarse = params.get(COARSE_VECTOR_NAME)
        late = params.get(LATE_VECTOR_NAME)
        if not isinstance(coarse, qdrant_models.VectorParams):
            raise RagConfigurationError(
                f"two-stage visual collection {self.collection_name!r} "
                "is missing the coarse vector"
            )
        if not isinstance(late, qdrant_models.VectorParams):
            raise RagConfigurationError(
                f"two-stage visual collection {self.collection_name!r} "
                "is missing the late-interaction vector"
            )
        late_multivector = getattr(late, "multivector_config", None)
        late_comparator = getattr(late_multivector, "comparator", None)
        if (
            coarse.size != self.dimension
            or coarse.distance != distance
            or getattr(coarse, "multivector_config", None) is not None
            or late.size != self.dimension
            or late.distance != distance
            or late_comparator != qdrant_models.MultiVectorComparator.MAX_SIM
        ):
            raise RagConfigurationError(
                "existing two-stage visual Qdrant schema mismatch: "
                f"expected coarse+MaxSim size={self.dimension}, "
                f"distance={distance.value}"
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
            raise RagVectorStoreError(
                "visual chunk/vector count mismatch: "
                f"{len(chunks)} chunks, {len(vectors)} vectors"
            )
        self.ensure_collection()
        old_ids = self._document_point_ids(document_id)
        points: list[qdrant_models.PointStruct] = []
        new_ids = set()
        for chunk, vector in zip(chunks, vectors, strict=True):
            multivector = _validate_multivector(vector, self.dimension)
            point_id = self._point_id(chunk.chunk_id)
            new_ids.add(point_id)
            payload = chunk.model_dump(mode="json")
            payload["source_kind"] = str(chunk.metadata.get("source_kind", ""))
            payload["visual_index_version"] = index_version
            payload["visual_search_schema"] = TWO_STAGE_VISUAL_SCHEMA_VERSION
            points.append(
                qdrant_models.PointStruct(
                    id=point_id,
                    vector={
                        COARSE_VECTOR_NAME: pool_multivector(multivector, self.dimension),
                        LATE_VECTOR_NAME: multivector,
                    },
                    payload=payload,
                )
            )

        try:
            if points:
                self._client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            stale = sorted(old_ids - new_ids, key=str)
            if stale:
                self._client.delete(
                    collection_name=self.collection_name,
                    points_selector=qdrant_models.PointIdsList(points=stale),
                    wait=True,
                )
        except Exception as exc:
            raise RagVectorStoreError(
                "failed to replace two-stage visual Qdrant document"
            ) from exc

    def search(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[RetrievalCandidate]:
        if top_k <= 0:
            raise RagVectorStoreError("visual top_k must be positive")
        self.ensure_collection()
        multivector = _validate_multivector(query, self.dimension)
        query_filter = self._build_filter(filters)

        if not self._config.prefetch_enabled:
            return self._full_scan(
                multivector,
                top_k=top_k,
                query_filter=query_filter,
                mode="full-maxsim",
            )

        prefetch_limit = max(top_k, self._config.prefetch_top_k)
        try:
            response = self._client.query_points(
                collection_name=self.collection_name,
                prefetch=qdrant_models.Prefetch(
                    query=pool_multivector(multivector, self.dimension),
                    using=COARSE_VECTOR_NAME,
                    limit=prefetch_limit,
                ),
                query=multivector,
                using=LATE_VECTOR_NAME,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
            return self._decode_candidates(
                response.points,
                mode="coarse-prefetch-maxsim",
                prefetch_limit=prefetch_limit,
            )
        except Exception as prefetch_exc:
            if not self._config.prefetch_fallback_to_full_scan:
                raise RagVectorStoreError(
                    "failed to run two-stage visual Qdrant search"
                ) from prefetch_exc
            fallback_reason = str(prefetch_exc) or prefetch_exc.__class__.__name__

        try:
            return self._full_scan(
                multivector,
                top_k=top_k,
                query_filter=query_filter,
                mode="full-maxsim-fallback",
                prefetch_limit=prefetch_limit,
                fallback_reason=fallback_reason,
            )
        except Exception as full_scan_exc:
            raise RagVectorStoreError(
                "two-stage visual search and full MaxSim fallback both failed: "
                f"prefetch={fallback_reason}; "
                f"full_scan={str(full_scan_exc) or full_scan_exc.__class__.__name__}"
            ) from full_scan_exc

    def _full_scan(
        self,
        multivector: list[list[float]],
        *,
        top_k: int,
        query_filter: qdrant_models.Filter | None,
        mode: str,
        prefetch_limit: int = 0,
        fallback_reason: str = "",
    ) -> list[RetrievalCandidate]:
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=multivector,
            using=LATE_VECTOR_NAME,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        return self._decode_candidates(
            response.points,
            mode=mode,
            prefetch_limit=prefetch_limit,
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def _decode_candidates(
        points: Sequence[Any],
        *,
        mode: str,
        prefetch_limit: int = 0,
        fallback_reason: str = "",
    ) -> list[RetrievalCandidate]:
        results: list[RetrievalCandidate] = []
        for rank, point in enumerate(points, start=1):
            payload = dict(point.payload or {})
            payload.pop("source_kind", None)
            payload.pop("visual_index_version", None)
            payload.pop("visual_search_schema", None)
            try:
                chunk = DocumentChunk.model_validate(payload)
            except Exception as exc:
                raise RagVectorStoreError(
                    "two-stage visual Qdrant point has invalid payload"
                ) from exc
            results.append(
                RetrievalCandidate(
                    chunk=chunk,
                    fusion_score=None,
                    rank=rank,
                    metadata={
                        "retrieval_channel": "visual",
                        "visual_score": float(point.score),
                        "visual_search_mode": mode,
                        "visual_prefetch_limit": prefetch_limit,
                        "visual_prefetch_fallback_reason": fallback_reason,
                    },
                )
            )
        return results


def pool_multivector(
    vector: Sequence[Sequence[float]],
    dimension: int,
) -> list[float]:
    """Build a cheap normalized centroid for first-stage visual recall."""

    rows = _validate_multivector(vector, dimension)
    pooled = [
        sum(row[index] for row in rows) / len(rows)
        for index in range(dimension)
    ]
    norm = math.sqrt(sum(value * value for value in pooled))
    if norm <= 1e-12:
        raise RagVectorStoreError(
            "cannot build a coarse visual vector from a zero-energy multivector"
        )
    return [value / norm for value in pooled]


def _validate_multivector(
    vector: Sequence[Sequence[float]],
    dimension: int,
) -> list[list[float]]:
    if not vector:
        raise RagVectorStoreError(
            "multivector must contain at least one token vector"
        )
    converted: list[list[float]] = []
    for row in vector:
        if len(row) != dimension:
            raise RagVectorStoreError(
                f"multivector dimension mismatch: expected {dimension}, got {len(row)}"
            )
        try:
            values = [float(value) for value in row]
        except (TypeError, ValueError) as exc:
            raise RagVectorStoreError(
                "multivector contains a non-numeric value"
            ) from exc
        if not all(math.isfinite(value) for value in values):
            raise RagVectorStoreError("multivector contains non-finite values")
        converted.append(values)
    return converted


def create_visual_vector_store(
    config: RagVisualRetrievalConfig,
    *,
    client: QdrantClient | None = None,
) -> QdrantVisualMultiVectorStore:
    """Select the Stage 3 or Stage 3.1 Qdrant visual store."""

    if config.prefetch_enabled:
        return QdrantTwoStageVisualStore(config, client=client)
    return QdrantVisualMultiVectorStore(config, client=client)


__all__ = [
    "COARSE_VECTOR_NAME",
    "LATE_VECTOR_NAME",
    "QdrantTwoStageVisualStore",
    "TWO_STAGE_VISUAL_SCHEMA_VERSION",
    "create_visual_vector_store",
    "pool_multivector",
]
