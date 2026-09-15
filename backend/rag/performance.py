from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any

from pydantic import Field, model_validator

from backend.rag.config import RagConfig
from backend.rag.evaluation import RagEvaluationReport, percentile
from backend.rag.models import RagContractModel


class RagPerformanceVariant(RagContractModel):
    name: str = Field(min_length=1)
    variable: str = "baseline"
    embedding_batch_size: int = Field(default=8, ge=1)
    precision: str = "default"
    embedding_dimension: int = Field(default=1024, ge=1)
    chunk_target_tokens: int = Field(default=512, ge=1)
    chunk_overlap_tokens: int = Field(default=80, ge=0)
    final_top_k: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def validate_variant(self) -> RagPerformanceVariant:
        if self.precision not in {"default", "fp16", "bf16"}:
            raise ValueError("unsupported benchmark precision")
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("chunk overlap must be smaller than target")
        return self


BASELINE_VARIANT = RagPerformanceVariant(name="baseline")


class RagEmbeddingBenchmark(RagContractModel):
    total_chunks: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0.0)
    chunks_per_second: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)
    peak_vram_mb: float | None = Field(default=None, ge=0.0)


class RagPerformanceCandidate(RagContractModel):
    variant: RagPerformanceVariant
    evaluation: RagEvaluationReport
    embedding: RagEmbeddingBenchmark


class RagPerformanceComparison(RagContractModel):
    baseline_name: str
    candidate_name: str
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    recall_at_10_delta: float
    ndcg_at_10_delta: float
    chunks_per_second_delta: float
    total_rag_p95_delta_ms: float


def performance_sweeps() -> dict[str, list[RagPerformanceVariant]]:
    fields: dict[str, list[Any]] = {
        "embedding_batch_size": [8, 16, 32],
        "precision": ["default", "fp16", "bf16"],
        "embedding_dimension": [1024, 768, 512, 256],
        "chunk_target_tokens": [512, 384, 768],
        "chunk_overlap_tokens": [80, 48, 128],
        "final_top_k": [8, 4, 12],
    }
    sweeps: dict[str, list[RagPerformanceVariant]] = {}
    baseline = BASELINE_VARIANT.model_dump()
    for field, values in fields.items():
        variants = []
        for value in values:
            payload = {
                **baseline,
                "name": f"{field}={value}",
                "variable": field,
                field: value,
            }
            variants.append(RagPerformanceVariant.model_validate(payload))
        sweeps[field] = variants
    return sweeps


def changed_variant_fields(
    variant: RagPerformanceVariant,
    baseline: RagPerformanceVariant = BASELINE_VARIANT,
) -> list[str]:
    tunable = (
        "embedding_batch_size",
        "precision",
        "embedding_dimension",
        "chunk_target_tokens",
        "chunk_overlap_tokens",
        "final_top_k",
    )
    return [
        field
        for field in tunable
        if getattr(variant, field) != getattr(baseline, field)
    ]


def validate_one_factor_variant(
    variant: RagPerformanceVariant,
    baseline: RagPerformanceVariant = BASELINE_VARIANT,
) -> None:
    changed = changed_variant_fields(variant, baseline)
    if len(changed) > 1:
        raise ValueError(
            "performance variants must change at most one variable; changed: "
            + ", ".join(changed)
        )
    if changed and variant.variable != changed[0]:
        raise ValueError("variant variable does not match the changed field")


def config_for_variant(
    variant: RagPerformanceVariant,
    baseline: RagConfig | None = None,
) -> RagConfig:
    validate_one_factor_variant(variant)
    config = baseline or RagConfig()
    updated = config.model_copy(
        update={
            "embedding": config.embedding.model_copy(
                update={
                    "batch_size": variant.embedding_batch_size,
                    "precision": variant.precision,
                    "dimension": variant.embedding_dimension,
                }
            ),
            "chunking": config.chunking.model_copy(
                update={
                    "target_tokens": variant.chunk_target_tokens,
                    "overlap_tokens": variant.chunk_overlap_tokens,
                }
            ),
            "retrieval": config.retrieval.model_copy(
                update={"final_top_k": variant.final_top_k}
            ),
        }
    )
    return RagConfig.model_validate(updated.model_dump())


def benchmark_embedding_batches(
    provider: Any,
    texts: Sequence[str],
    *,
    batch_size: int,
    rounds: int = 1,
) -> RagEmbeddingBenchmark:
    if batch_size < 1 or rounds < 1:
        raise ValueError("batch_size and rounds must be positive")
    if not texts:
        return RagEmbeddingBenchmark(
            total_chunks=0,
            elapsed_ms=0,
            chunks_per_second=0,
            p95_ms=0,
        )
    latencies: list[float] = []
    total_chunks = 0
    started = perf_counter()
    for _round in range(rounds):
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            batch_started = perf_counter()
            provider.embed_documents(batch)
            latencies.append((perf_counter() - batch_started) * 1000)
            total_chunks += len(batch)
    elapsed_ms = (perf_counter() - started) * 1000
    runtime = getattr(provider, "runtime", None)
    peak_vram = getattr(runtime, "allocated_vram_mb", None)
    return RagEmbeddingBenchmark(
        total_chunks=total_chunks,
        elapsed_ms=elapsed_ms,
        chunks_per_second=(total_chunks / (elapsed_ms / 1000) if elapsed_ms > 0 else 0),
        p95_ms=percentile(latencies, 95),
        peak_vram_mb=peak_vram,
    )


def compare_performance_candidates(
    baseline: RagPerformanceCandidate,
    candidate: RagPerformanceCandidate,
    *,
    max_recall_drop: float = 0.02,
    max_ndcg_drop: float = 0.02,
) -> RagPerformanceComparison:
    if max_recall_drop < 0 or max_ndcg_drop < 0:
        raise ValueError("quality-drop budgets must be non-negative")
    validate_one_factor_variant(candidate.variant, baseline.variant)
    recall_delta = (
        candidate.evaluation.retrieval.recall_at_10
        - baseline.evaluation.retrieval.recall_at_10
    )
    ndcg_delta = (
        candidate.evaluation.retrieval.ndcg_at_10
        - baseline.evaluation.retrieval.ndcg_at_10
    )
    throughput_delta = (
        candidate.embedding.chunks_per_second - baseline.embedding.chunks_per_second
    )
    latency_delta = (
        candidate.evaluation.performance.total_rag_ms.p95
        - baseline.evaluation.performance.total_rag_ms.p95
    )
    reasons: list[str] = []
    if recall_delta < -max_recall_drop:
        reasons.append("Recall@10 regression exceeds quality budget")
    if ndcg_delta < -max_ndcg_drop:
        reasons.append("nDCG@10 regression exceeds quality budget")
    if throughput_delta <= 0 and latency_delta >= 0:
        reasons.append(
            "candidate has no measured throughput or p95 latency improvement"
        )
    return RagPerformanceComparison(
        baseline_name=baseline.variant.name,
        candidate_name=candidate.variant.name,
        eligible=not reasons,
        reasons=reasons,
        recall_at_10_delta=recall_delta,
        ndcg_at_10_delta=ndcg_delta,
        chunks_per_second_delta=throughput_delta,
        total_rag_p95_delta_ms=latency_delta,
    )


__all__ = [
    "BASELINE_VARIANT",
    "RagEmbeddingBenchmark",
    "RagPerformanceCandidate",
    "RagPerformanceComparison",
    "RagPerformanceVariant",
    "benchmark_embedding_batches",
    "changed_variant_fields",
    "compare_performance_candidates",
    "config_for_variant",
    "performance_sweeps",
    "validate_one_factor_variant",
]
