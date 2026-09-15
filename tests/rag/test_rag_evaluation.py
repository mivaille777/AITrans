from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rag.evaluation import (
    evaluate_rag,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from backend.rag.evaluation_dataset import (
    RagClaimPrediction,
    RagEvaluationCase,
    RagEvaluationClaim,
    RagEvaluationLatency,
    RagEvaluationPrediction,
    load_evaluation_dataset,
    load_evaluation_predictions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cases() -> list[RagEvaluationCase]:
    return [
        RagEvaluationCase(
            case_id="term-1",
            query="What is an encoder?",
            categories=["term"],
            relevant_chunk_ids=["chunk-a", "chunk-b"],
            relevance_grades={"chunk-a": 3, "chunk-b": 1},
            claims=[
                RagEvaluationClaim(claim_id="claim-a", relevant_chunk_ids=["chunk-a"]),
                RagEvaluationClaim(claim_id="claim-b", relevant_chunk_ids=["chunk-b"]),
            ],
        ),
        RagEvaluationCase(
            case_id="cross-1",
            query="Compare the methods across sections.",
            categories=["cross_section", "multi_document"],
            relevant_chunk_ids=["chunk-c"],
        ),
        RagEvaluationCase(
            case_id="none-1",
            query="Which result is not present?",
            categories=["no_answer"],
            no_answer=True,
        ),
    ]


def _predictions() -> list[RagEvaluationPrediction]:
    return [
        RagEvaluationPrediction(
            case_id="term-1",
            pre_rerank_chunk_ids=["noise", "chunk-a", "chunk-b"],
            ranked_chunk_ids=["chunk-a", "chunk-b"],
            claims=[
                RagClaimPrediction(
                    claim_id="claim-a",
                    cited_chunk_ids=["chunk-a"],
                    supported=True,
                ),
                RagClaimPrediction(
                    claim_id="claim-b",
                    cited_chunk_ids=["noise"],
                    supported=False,
                ),
            ],
            latency=RagEvaluationLatency(
                query_embedding_ms=1,
                dense_search_ms=2,
                bm25_ms=3,
                rerank_ms=4,
                total_rag_ms=10,
            ),
        ),
        RagEvaluationPrediction(
            case_id="cross-1",
            pre_rerank_chunk_ids=["noise-a", "noise-b", "chunk-c"],
            ranked_chunk_ids=["noise-a", "chunk-c"],
            latency=RagEvaluationLatency(
                query_embedding_ms=2,
                dense_search_ms=4,
                bm25_ms=6,
                rerank_ms=8,
                total_rag_ms=20,
            ),
        ),
        RagEvaluationPrediction(
            case_id="none-1",
            pre_rerank_chunk_ids=[],
            ranked_chunk_ids=[],
            latency=RagEvaluationLatency(
                query_embedding_ms=3,
                dense_search_ms=6,
                bm25_ms=9,
                rerank_ms=12,
                total_rag_ms=30,
            ),
        ),
    ]


def test_retrieval_metric_primitives_cover_binary_and_graded_relevance() -> None:
    ranked = ["noise", "chunk-a", "chunk-b"]

    assert recall_at_k(ranked, ["chunk-a", "chunk-b"], 2) == 0.5
    assert reciprocal_rank(ranked, ["chunk-a"]) == 0.5
    assert ndcg_at_k(ranked, {"chunk-a": 3, "chunk-b": 1}, 10) == pytest.approx(
        0.6443, abs=0.0001
    )
    assert percentile([10, 20, 30], 95) == 29


def test_evaluation_reports_retrieval_reranking_grounding_and_latency() -> None:
    report = evaluate_rag(_cases(), _predictions())

    assert report.total_cases == 3
    assert report.category_counts == {
        "cross_section": 1,
        "multi_document": 1,
        "no_answer": 1,
        "term": 1,
    }
    assert report.retrieval.evaluated_cases == 2
    assert report.retrieval.recall_at_5 == 1
    assert report.retrieval.no_answer_accuracy == 1
    assert report.reranker.mrr_before == pytest.approx((0.5 + 1 / 3) / 2)
    assert report.reranker.mrr_after == 0.75
    assert report.reranker.mrr_delta > 0
    assert report.citations.citation_precision == 0.5
    assert report.citations.citation_recall == 0.5
    assert report.citations.citation_coverage == 1
    assert report.citations.unsupported_claim_rate == 0.5
    assert report.citations.assessed_claims == 2
    assert report.performance.total_rag_ms.p50 == 20
    assert report.performance.total_rag_ms.p95 == 29


def test_evaluation_requires_exact_case_prediction_alignment() -> None:
    with pytest.raises(ValueError, match="missing predictions: cross-1, none-1"):
        evaluate_rag(_cases(), _predictions()[:1])


def test_dataset_contract_rejects_invalid_no_answer_and_duplicate_rankings() -> None:
    with pytest.raises(ValidationError, match="no-answer cases cannot"):
        RagEvaluationCase(
            case_id="bad",
            query="bad",
            categories=["no_answer"],
            no_answer=True,
            relevant_chunk_ids=["chunk-a"],
        )
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        RagEvaluationPrediction(case_id="bad", ranked_chunk_ids=["chunk-a", "chunk-a"])


def test_jsonl_loaders_and_cli_emit_a_machine_readable_report(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    report_path = tmp_path / "report.json"
    dataset_path.write_text(
        "\n".join(case.model_dump_json() for case in _cases()), encoding="utf-8"
    )
    predictions_path.write_text(
        "\n".join(item.model_dump_json() for item in _predictions()), encoding="utf-8"
    )

    assert len(load_evaluation_dataset(dataset_path)) == 3
    assert len(load_evaluation_predictions(predictions_path)) == 3
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_rag.py",
            "--dataset",
            str(dataset_path),
            "--predictions",
            str(predictions_path),
            "--output",
            str(report_path),
            "--fail-below-recall-at-10",
            "1.0",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["retrieval"]["recall_at_10"] == 1
    assert json.loads(completed.stdout)["total_cases"] == 3
