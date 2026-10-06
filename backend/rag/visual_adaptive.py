from __future__ import annotations

import math
import os
from collections.abc import Sequence
from dataclasses import dataclass

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import RetrievalCandidate, RetrievalResult
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.stores.local_repository import LocalVectorRepository
from backend.rag.stores.visual_base import VisualVectorStore
from backend.rag.visual_retrieval import VisualRetrievalService


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
    def from_environment(cls) -> AdaptivePrefetchPolicy:
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
        **retrieval_options,
    ) -> RetrievalResult:
        result = super().retrieve(
            query,
            filters=filters,
            section_hints=section_hints,
            final_top_k=final_top_k,
            include_references=include_references,
            **retrieval_options,
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
    config: RagVisualRetrievalConfig, *, repository: LocalVectorRepository | None = None,
    policy: AdaptivePrefetchPolicy | None = None,
) -> VisualVectorStore:
    from backend.rag.stores.faiss_visual import FaissVisualMultiVectorStore
    return FaissVisualMultiVectorStore(config, repository=repository, policy=policy)


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
    "AdaptiveVisualRetrievalService",
    "adaptive_prefetch_top_k",
    "create_adaptive_visual_vector_store",
]
