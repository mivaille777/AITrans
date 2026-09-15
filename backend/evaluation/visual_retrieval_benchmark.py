from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.visual_adaptive import AdaptiveQdrantTwoStageVisualStore
from backend.rag.visual_retrieval import VisualEmbeddingProvider


class VisualRetrievalBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    relevant_chunk_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("benchmark query must not be empty")
        return normalized


class VisualRetrievalBenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    mode: str
    prefetch_k: int | None = None
    relevance_source: str
    recall_at_k: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    latency_ms: tuple[float, ...]
    p50_latency_ms: float
    p95_latency_ms: float
    candidate_count: int | None = None
    maxsim_candidate_reduction: float | None = None
    retrieved_chunk_ids: tuple[str, ...]


class VisualRetrievalBenchmarkModeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    case_count: int
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_maxsim_candidate_reduction: float | None = None


class VisualRetrievalBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    top_k: int
    repeats: int
    warmup: int
    fixed_prefetch_ks: tuple[int, ...]
    case_count: int
    query_embedding_p50_ms: float
    query_embedding_p95_ms: float
    full_maxsim_oracle_p50_ms: float
    full_maxsim_oracle_p95_ms: float
    cases: tuple[VisualRetrievalBenchmarkCaseResult, ...]
    summaries: tuple[VisualRetrievalBenchmarkModeSummary, ...]


def load_visual_retrieval_benchmark_cases(
    path: str | Path,
) -> tuple[VisualRetrievalBenchmarkCase, ...]:
    source = Path(path)
    cases: list[VisualRetrievalBenchmarkCase] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"benchmark line {line_number} must be a JSON object")
        payload.setdefault("case_id", f"case-{line_number:04d}")
        cases.append(VisualRetrievalBenchmarkCase.model_validate(payload))
    if not cases:
        raise ValueError("visual retrieval benchmark dataset is empty")
    return tuple(cases)


def run_visual_retrieval_benchmark(
    cases: Sequence[VisualRetrievalBenchmarkCase],
    *,
    provider: VisualEmbeddingProvider,
    store: AdaptiveQdrantTwoStageVisualStore,
    config: RagVisualRetrievalConfig,
    fixed_prefetch_ks: Sequence[int] = (24, 48, 96),
    top_k: int | None = None,
    repeats: int = 3,
    warmup: int = 1,
) -> VisualRetrievalBenchmarkReport:
    if not cases:
        raise ValueError("visual retrieval benchmark requires at least one case")
    if repeats <= 0 or warmup < 0:
        raise ValueError("repeats must be positive and warmup must be non-negative")
    desired_top_k = top_k or config.visual_top_k
    if desired_top_k <= 0:
        raise ValueError("top_k must be positive")
    normalized_ks = tuple(sorted({int(value) for value in fixed_prefetch_ks}))
    if not normalized_ks or any(value <= 0 for value in normalized_ks):
        raise ValueError("fixed prefetch values must be positive")

    fixed_stores = {
        value: store.fixed_prefetch_store(value)
        for value in normalized_ks
    }
    case_results: list[VisualRetrievalBenchmarkCaseResult] = []
    query_embedding_ms: list[float] = []
    full_maxsim_oracle_ms: list[float] = []

    for case in cases:
        filters = (
            VectorSearchFilter(document_ids=list(case.document_ids))
            if case.document_ids
            else None
        )
        started = perf_counter()
        query_vector = provider.embed_query(case.query)
        query_embedding_ms.append((perf_counter() - started) * 1000.0)

        oracle_started = perf_counter()
        oracle = store.search_full_maxsim(
            query_vector,
            top_k=desired_top_k,
            filters=filters,
        )
        full_maxsim_oracle_ms.append((perf_counter() - oracle_started) * 1000.0)
        oracle_ids = tuple(candidate.chunk.chunk_id for candidate in oracle)

        if case.relevant_chunk_ids:
            relevant_ids = tuple(dict.fromkeys(case.relevant_chunk_ids))
            relevance_source = "labeled"
        else:
            relevant_ids = oracle_ids
            relevance_source = "full_maxsim_oracle"

        modes: list[tuple[str, AdaptiveQdrantTwoStageVisualStore, int | None]] = [
            ("adaptive", store, None),
            *[
                (f"fixed_{prefetch_k}", fixed_stores[prefetch_k], prefetch_k)
                for prefetch_k in normalized_ks
            ],
        ]
        for mode, mode_store, configured_k in modes:
            for _ in range(warmup):
                mode_store.search(
                    query_vector,
                    top_k=desired_top_k,
                    filters=filters,
                )

            timings: list[float] = []
            retrieved = []
            for _ in range(repeats):
                search_started = perf_counter()
                retrieved = mode_store.search(
                    query_vector,
                    top_k=desired_top_k,
                    filters=filters,
                )
                timings.append((perf_counter() - search_started) * 1000.0)

            retrieved_ids = tuple(
                candidate.chunk.chunk_id for candidate in retrieved
            )
            first_metadata = retrieved[0].metadata if retrieved else {}
            candidate_count = _optional_int(first_metadata.get("visual_candidate_count"))
            reduction = _optional_float(
                first_metadata.get("visual_maxsim_candidate_reduction")
            )
            actual_prefetch_k = _optional_int(first_metadata.get("visual_prefetch_k"))
            case_results.append(
                VisualRetrievalBenchmarkCaseResult(
                    case_id=case.case_id,
                    mode=mode,
                    prefetch_k=actual_prefetch_k or configured_k,
                    relevance_source=relevance_source,
                    recall_at_k=recall_at_k(
                        retrieved_ids,
                        relevant_ids,
                        desired_top_k,
                    ),
                    reciprocal_rank=reciprocal_rank(
                        retrieved_ids,
                        relevant_ids,
                    ),
                    latency_ms=tuple(timings),
                    p50_latency_ms=percentile(timings, 50),
                    p95_latency_ms=percentile(timings, 95),
                    candidate_count=candidate_count,
                    maxsim_candidate_reduction=reduction,
                    retrieved_chunk_ids=retrieved_ids,
                )
            )

    summaries = _summarize_modes(case_results)
    return VisualRetrievalBenchmarkReport(
        generated_at=datetime.now(UTC),
        top_k=desired_top_k,
        repeats=repeats,
        warmup=warmup,
        fixed_prefetch_ks=normalized_ks,
        case_count=len(cases),
        query_embedding_p50_ms=percentile(query_embedding_ms, 50),
        query_embedding_p95_ms=percentile(query_embedding_ms, 95),
        full_maxsim_oracle_p50_ms=percentile(full_maxsim_oracle_ms, 50),
        full_maxsim_oracle_p95_ms=percentile(full_maxsim_oracle_ms, 95),
        cases=tuple(case_results),
        summaries=tuple(summaries),
    )


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    k: int,
) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    retrieved = set(retrieved_ids[:k])
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    if not 0.0 <= percentile_value <= 100.0:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summarize_modes(
    results: Sequence[VisualRetrievalBenchmarkCaseResult],
) -> list[VisualRetrievalBenchmarkModeSummary]:
    grouped: dict[str, list[VisualRetrievalBenchmarkCaseResult]] = {}
    for result in results:
        grouped.setdefault(result.mode, []).append(result)

    summaries: list[VisualRetrievalBenchmarkModeSummary] = []
    for mode in sorted(grouped):
        mode_results = grouped[mode]
        all_latencies = [
            latency
            for result in mode_results
            for latency in result.latency_ms
        ]
        reductions = [
            result.maxsim_candidate_reduction
            for result in mode_results
            if result.maxsim_candidate_reduction is not None
        ]
        summaries.append(
            VisualRetrievalBenchmarkModeSummary(
                mode=mode,
                case_count=len(mode_results),
                mean_recall_at_k=_mean(
                    result.recall_at_k for result in mode_results
                ),
                mean_reciprocal_rank=_mean(
                    result.reciprocal_rank for result in mode_results
                ),
                p50_latency_ms=percentile(all_latencies, 50),
                p95_latency_ms=percentile(all_latencies, 95),
                mean_maxsim_candidate_reduction=(
                    _mean(reductions) if reductions else None
                ),
            )
        )
    return summaries


def _mean(values: Iterable[float]) -> float:
    materialized = [float(value) for value in values]
    return sum(materialized) / len(materialized) if materialized else 0.0


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


__all__ = [
    "VisualRetrievalBenchmarkCase",
    "VisualRetrievalBenchmarkCaseResult",
    "VisualRetrievalBenchmarkModeSummary",
    "VisualRetrievalBenchmarkReport",
    "load_visual_retrieval_benchmark_cases",
    "percentile",
    "recall_at_k",
    "reciprocal_rank",
    "run_visual_retrieval_benchmark",
]
