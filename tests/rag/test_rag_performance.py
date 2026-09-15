from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
from backend.rag.evaluation import evaluate_rag
from backend.rag.evaluation_dataset import (
    RagEvaluationCase,
    RagEvaluationLatency,
    RagEvaluationPrediction,
)
from backend.rag.performance import (
    BASELINE_VARIANT,
    RagEmbeddingBenchmark,
    RagPerformanceCandidate,
    RagPerformanceVariant,
    benchmark_embedding_batches,
    changed_variant_fields,
    compare_performance_candidates,
    config_for_variant,
    performance_sweeps,
    validate_one_factor_variant,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeBatchProvider:
    runtime = SimpleNamespace(allocated_vram_mb=128.0)

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return [[1.0] for _text in texts]


class PrecisionTorch:
    float16 = object()
    bfloat16 = object()

    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False


class TruncatingModel:
    def __init__(self) -> None:
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return [[0.0] * kwargs["truncate_dim"] for _text in texts]


def _evaluation(ranked: list[str], *, total_ms: float):
    return evaluate_rag(
        [
            RagEvaluationCase(
                case_id="case-1",
                query="query",
                relevant_chunk_ids=["relevant"],
            )
        ],
        [
            RagEvaluationPrediction(
                case_id="case-1",
                ranked_chunk_ids=ranked,
                pre_rerank_chunk_ids=ranked,
                latency=RagEvaluationLatency(total_rag_ms=total_ms),
            )
        ],
    )


def _candidate(
    variant: RagPerformanceVariant,
    *,
    ranked: list[str],
    chunks_per_second: float,
    total_ms: float,
) -> RagPerformanceCandidate:
    return RagPerformanceCandidate(
        variant=variant,
        evaluation=_evaluation(ranked, total_ms=total_ms),
        embedding=RagEmbeddingBenchmark(
            total_chunks=10,
            elapsed_ms=100,
            chunks_per_second=chunks_per_second,
            p95_ms=10,
        ),
    )


def test_sweeps_cover_required_values_and_only_change_one_factor() -> None:
    sweeps = performance_sweeps()

    assert [item.embedding_batch_size for item in sweeps["embedding_batch_size"]] == [
        8,
        16,
        32,
    ]
    assert [item.precision for item in sweeps["precision"]] == [
        "default",
        "fp16",
        "bf16",
    ]
    assert [item.embedding_dimension for item in sweeps["embedding_dimension"]] == [
        1024,
        768,
        512,
        256,
    ]
    assert [item.chunk_target_tokens for item in sweeps["chunk_target_tokens"]] == [
        512,
        384,
        768,
    ]
    assert [item.chunk_overlap_tokens for item in sweeps["chunk_overlap_tokens"]] == [
        80,
        48,
        128,
    ]
    assert [item.final_top_k for item in sweeps["final_top_k"]] == [8, 4, 12]
    for variants in sweeps.values():
        for variant in variants:
            validate_one_factor_variant(variant)
            assert len(changed_variant_fields(variant)) <= 1


def test_variant_configuration_keeps_frozen_defaults_until_explicitly_changed() -> None:
    baseline = config_for_variant(BASELINE_VARIANT)
    smaller = config_for_variant(
        RagPerformanceVariant(
            name="dimension=512",
            variable="embedding_dimension",
            embedding_dimension=512,
        )
    )

    assert baseline.embedding.dimension == 1024
    assert baseline.embedding.batch_size == 8
    assert baseline.embedding.precision == "default"
    assert baseline.chunking.target_tokens == 512
    assert baseline.chunking.overlap_tokens == 80
    assert baseline.retrieval.final_top_k == 8
    assert smaller.embedding.dimension == 512
    assert smaller.chunking == baseline.chunking


def test_embedding_benchmark_records_throughput_batches_p95_and_vram() -> None:
    provider = FakeBatchProvider()

    result = benchmark_embedding_batches(
        provider,
        [f"chunk-{index}" for index in range(10)],
        batch_size=4,
        rounds=2,
    )

    assert provider.batch_sizes == [4, 4, 2, 4, 4, 2]
    assert result.total_chunks == 20
    assert result.chunks_per_second > 0
    assert result.p95_ms >= 0
    assert result.peak_vram_mb == 128


def test_candidate_requires_quality_budget_and_measured_speed_improvement() -> None:
    baseline = _candidate(
        BASELINE_VARIANT,
        ranked=["relevant"],
        chunks_per_second=100,
        total_ms=100,
    )
    variant = RagPerformanceVariant(
        name="batch=16",
        variable="embedding_batch_size",
        embedding_batch_size=16,
    )
    accepted = compare_performance_candidates(
        baseline,
        _candidate(
            variant,
            ranked=["relevant"],
            chunks_per_second=120,
            total_ms=90,
        ),
    )
    rejected = compare_performance_candidates(
        baseline,
        _candidate(
            variant,
            ranked=["noise"],
            chunks_per_second=150,
            total_ms=70,
        ),
    )

    assert accepted.eligible is True
    assert accepted.chunks_per_second_delta == 20
    assert accepted.total_rag_p95_delta_ms == -10
    assert rejected.eligible is False
    assert any("Recall@10" in reason for reason in rejected.reasons)
    assert any("nDCG@10" in reason for reason in rejected.reasons)


def test_multi_factor_candidate_is_rejected() -> None:
    variant = RagPerformanceVariant(
        name="invalid",
        variable="embedding_batch_size",
        embedding_batch_size=16,
        embedding_dimension=512,
    )
    with pytest.raises(ValueError, match="at most one variable"):
        validate_one_factor_variant(variant)


def test_precision_and_truncated_dimension_are_forwarded_to_runtime() -> None:
    model = TruncatingModel()
    factory_calls = []

    def factory(*args, **kwargs):
        factory_calls.append((args, kwargs))
        return model

    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(
            dimension=256,
            device="cpu",
            warmup=False,
            precision="fp16",
        ),
        model_factory=factory,
        torch_module=PrecisionTorch(),
    )

    assert len(provider.embed_query("query")) == 256
    assert factory_calls[0][1]["model_kwargs"]["torch_dtype"] is PrecisionTorch.float16
    assert model.calls[0][1]["truncate_dim"] == 256


def test_benchmark_cli_lists_machine_readable_variants() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_rag.py", "--list-variants"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert len(payload["embedding_dimension"]) == 4
    assert payload["final_top_k"][1]["final_top_k"] == 4
