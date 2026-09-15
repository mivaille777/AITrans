from __future__ import annotations

import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.visual_prefetch import (
    COARSE_VECTOR_NAME,
    LATE_VECTOR_NAME,
    QdrantTwoStageVisualStore,
    pool_multivector,
)
from backend.rag.visual_retrieval import (
    QdrantVisualMultiVectorStore,
    VisualRetrievalService,
    _validate_multivector,
)


@dataclass(frozen=True, slots=True)
class AdaptivePrefetchPolicy:
    """Query-time policy for sizing the coarse visual candidate pool."""

    enabled: bool = True
    min_k: int = 24
    max_k: int = 96
    candidate_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.min_k <= 0:
            raise ValueError("adaptive prefetch min_k must be positive")
        if self.max_k < self.min_k:
            raise ValueError("adaptive prefetch max_k must be >= min_k")
        if not 0.0 < self.candidate_ratio <= 1.0:
            raise ValueError("adaptive prefetch candidate_ratio must be in (0, 1]")

    @classmethod
    def from_environment(cls) -> "AdaptivePrefetchPolicy":
        return cls(
            enabled=_env_bool(
                "AITRANS_RAG_VISUAL_ADAPTIVE_PREFETCH_ENABLED",
                default=True,
            ),
            min_k=_env_int("AITRANS_RAG_VISUAL_ADAPTIVE_PREFETCH_MIN_K", default=24),
            max_k=_env_int("AITRANS_RAG_VISUAL_ADAPTIVE_PREFETCH_MAX_K", default=96),
            candidate_ratio=_env_float(
                "AITRANS_RAG_VISUAL_ADAPTIVE_PREFETCH_RATIO",
                default=0.25,
            ),
        )


def adaptive_prefetch_top_k(
    *,
    candidate_count: int | None,
    visual_top_k: int,
    fallback_prefetch_k: int,
    policy: AdaptivePrefetchPolicy,
) -> int:
    """Choose a bounded prefetch pool without changing the visual index."""

    fallback = max(1, visual_top_k, fallback_prefetch_k)
    if not policy.enabled or candidate_count is None or candidate_count <= 0:
        return fallback

    proportional = math.ceil(candidate_count * policy.candidate_ratio)
    target = max(visual_top_k, policy.min_k, proportional)
    target = min(target, policy.max_k, candidate_count)
    return max(1, target)


class AdaptiveQdrantTwoStageVisualStore(QdrantTwoStageVisualStore):
    """Stage 3.2 visual store with corpus-aware coarse candidate sizing."""

    def __init__(
        self,
        config: RagVisualRetrievalConfig,
        *,
        client: QdrantClient | None = None,
        policy: AdaptivePrefetchPolicy | None = None,
    ) -> None:
        super().__init__(config, client=client)
        self._prefetch_policy = policy or AdaptivePrefetchPolicy.from_environment()

    @property
    def prefetch_policy(self) -> AdaptivePrefetchPolicy:
        return self._prefetch_policy

    def estimate_candidate_count(
        self,
        filters: VectorSearchFilter | None = None,
    ) -> int | None:
        """Best-effort filtered point count used only for query planning."""

        try:
            response = self._client.count(
                collection_name=self.collection_name,
                count_filter=self._build_filter(filters),
                exact=False,
            )
            value = int(getattr(response, "count", 0) or 0)
        except Exception:
            return None
        return max(0, value)

    def search(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[RetrievalCandidate]:
        if not self._prefetch_policy.enabled:
            candidate_count = self.estimate_candidate_count(filters)
            results = super().search(query, top_k=top_k, filters=filters)
            return _annotate_prefetch_results(
                results,
                candidate_count=candidate_count,
                prefetch_k=max(
                    top_k,
                    max(self._config.visual_top_k, self._config.prefetch_top_k),
                ),
                adaptive=False,
            )

        if top_k <= 0:
            raise ValueError("visual top_k must be positive")
        self.ensure_collection()
        multivector = _validate_multivector(query, self.dimension)
        query_filter = self._build_filter(filters)
        candidate_count = self.estimate_candidate_count(filters)
        prefetch_limit = adaptive_prefetch_top_k(
            candidate_count=candidate_count,
            visual_top_k=top_k,
            fallback_prefetch_k=max(
                self._config.visual_top_k,
                self._config.prefetch_top_k,
            ),
            policy=self._prefetch_policy,
        )
        started = perf_counter()
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
            results = self._decode_candidates(
                response.points,
                mode="adaptive-coarse-prefetch-maxsim",
                prefetch_limit=prefetch_limit,
            )
        except Exception as prefetch_exc:
            if not self._config.prefetch_fallback_to_full_scan:
                raise
            fallback_reason = str(prefetch_exc) or prefetch_exc.__class__.__name__
            results = self._full_scan(
                multivector,
                top_k=top_k,
                query_filter=query_filter,
                mode="full-maxsim-fallback",
                prefetch_limit=prefetch_limit,
                fallback_reason=fallback_reason,
            )
        elapsed_ms = (perf_counter() - started) * 1000.0
        return _annotate_prefetch_results(
            results,
            candidate_count=candidate_count,
            prefetch_k=prefetch_limit,
            adaptive=True,
            search_ms=elapsed_ms,
        )

    def search_full_maxsim(
        self,
        query: list[list[float]],
        *,
        top_k: int,
        filters: VectorSearchFilter | None = None,
    ) -> list[RetrievalCandidate]:
        """Full-collection Qdrant MaxSim used as the benchmark oracle."""

        if top_k <= 0:
            raise ValueError("visual top_k must be positive")
        self.ensure_collection()
        multivector = _validate_multivector(query, self.dimension)
        results = self._full_scan(
            multivector,
            top_k=top_k,
            query_filter=self._build_filter(filters),
            mode="full-maxsim-oracle",
        )
        candidate_count = self.estimate_candidate_count(filters)
        return _annotate_prefetch_results(
            results,
            candidate_count=candidate_count,
            prefetch_k=candidate_count or top_k,
            adaptive=False,
        )

    def fixed_prefetch_store(self, prefetch_k: int) -> "AdaptiveQdrantTwoStageVisualStore":
        """Share the collection/client while disabling adaptive sizing for A/B tests."""

        if prefetch_k <= 0:
            raise ValueError("prefetch_k must be positive")
        config = self._config.model_copy(
            update={"prefetch_top_k": max(self._config.visual_top_k, prefetch_k)},
            deep=True,
        )
        return AdaptiveQdrantTwoStageVisualStore(
            config,
            client=self._client,
            policy=AdaptivePrefetchPolicy(
                enabled=False,
                min_k=self._prefetch_policy.min_k,
                max_k=self._prefetch_policy.max_k,
                candidate_ratio=self._prefetch_policy.candidate_ratio,
            ),
        )


class AdaptiveVisualRetrievalService(VisualRetrievalService):
    """Surface Stage 3.2 query-planning metrics on the RetrievalResult."""

    def retrieve(
        self,
        query: str,
        *,
        filters: VectorSearchFilter | None = None,
        section_hints: tuple[str, ...] = (),
        final_top_k: int | None = None,
        include_references: bool = False,
    ) -> RetrievalResult:
        result = super().retrieve(
            query,
            filters=filters,
            section_hints=section_hints,
            final_top_k=final_top_k,
            include_references=include_references,
        )
        metadata = dict(result.metadata)
        policy = getattr(self._store, "prefetch_policy", None)
        if isinstance(policy, AdaptivePrefetchPolicy):
            metadata.update(
                {
                    "visual_adaptive_prefetch_enabled": policy.enabled,
                    "visual_adaptive_prefetch_min_k": policy.min_k,
                    "visual_adaptive_prefetch_max_k": policy.max_k,
                    "visual_adaptive_prefetch_ratio": policy.candidate_ratio,
                }
            )

        for candidate in result.candidates:
            candidate_metadata = candidate.metadata
            if "visual_prefetch_k" not in candidate_metadata:
                continue
            for key in (
                "visual_search_mode",
                "visual_prefetch_k",
                "visual_candidate_count",
                "visual_prefetch_adaptive",
                "visual_maxsim_candidate_reduction",
                "visual_store_search_ms",
            ):
                if key in candidate_metadata:
                    metadata[key] = candidate_metadata[key]
            break
        return result.model_copy(update={"metadata": metadata})


def create_adaptive_visual_vector_store(
    config: RagVisualRetrievalConfig,
    *,
    client: QdrantClient | None = None,
    policy: AdaptivePrefetchPolicy | None = None,
) -> QdrantVisualMultiVectorStore:
    """Create Stage 3.2 when Stage 3.1 prefetch is enabled, else Stage 3."""

    if not config.prefetch_enabled:
        return QdrantVisualMultiVectorStore(config, client=client)
    return AdaptiveQdrantTwoStageVisualStore(
        config,
        client=client,
        policy=policy,
    )


def _annotate_prefetch_results(
    results: Sequence[RetrievalCandidate],
    *,
    candidate_count: int | None,
    prefetch_k: int,
    adaptive: bool,
    search_ms: float | None = None,
) -> list[RetrievalCandidate]:
    actual_prefetch = prefetch_k
    if candidate_count is not None and candidate_count > 0:
        actual_prefetch = min(actual_prefetch, candidate_count)
    reduction: float | None = None
    if candidate_count is not None and candidate_count > 0:
        reduction = max(0.0, 1.0 - (actual_prefetch / candidate_count))

    output: list[RetrievalCandidate] = []
    for candidate in results:
        mode = str(candidate.metadata.get("visual_search_mode", ""))
        effective_reduction = 0.0 if mode.startswith("full-maxsim") else reduction
        metadata = {
            **candidate.metadata,
            "visual_prefetch_k": actual_prefetch,
            "visual_candidate_count": candidate_count,
            "visual_prefetch_adaptive": adaptive,
            "visual_maxsim_candidate_reduction": effective_reduction,
        }
        if search_ms is not None:
            metadata["visual_store_search_ms"] = search_ms
        output.append(candidate.model_copy(update={"metadata": metadata}))
    return output


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "").strip().casefold()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


__all__ = [
    "AdaptivePrefetchPolicy",
    "AdaptiveQdrantTwoStageVisualStore",
    "AdaptiveVisualRetrievalService",
    "adaptive_prefetch_top_k",
    "create_adaptive_visual_vector_store",
]
