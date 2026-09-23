from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.rag.benchmarks.qasper.protocol import (
    audit_qasper_run,
    compare_qasper_runs,
)


def _write_run(
    directory: Path,
    *,
    question_id: str = "q1",
    source_path: Path,
    answer_f1: float = 0.5,
    final_document_id: str = "qasper:validation:p1",
) -> Path:
    directory.mkdir(parents=True)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    qrels_path = directory.parent / f"qrels-{directory.name}.jsonl"
    qrels_path.write_text(
        json.dumps({"question_id": question_id, "paper_id": "p1"}) + "\n",
        encoding="utf-8",
    )
    record = {"question_id": question_id}
    (directory / "predictions.jsonl").write_text(
        json.dumps(
            {
                **record,
                "answer": "answer",
                "predicted_evidence": [],
                "answer_generation": {"provider": "deepseek", "model": "test"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "retrieval_trace.jsonl").write_text(
        json.dumps(
            {
                **record,
                "scope_document_id": "qasper:validation:p1",
                "retrieval_metadata": {
                    "dense_count": 1,
                    "sparse_count": 1,
                    "reranker_applied": True,
                },
                "final_candidates": [
                    {"chunk_id": "chunk-1", "document_id": final_document_id}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "errors.jsonl").write_text("", encoding="utf-8")
    (directory / "metrics.json").write_text(
        json.dumps(
            {
                "question_count": 1,
                "prediction_count": 1,
                "trace_count": 1,
                "per_question": [
                    {
                        "question_id": question_id,
                        "official_answer_f1": answer_f1,
                        "official_evidence_f1": 0.25,
                        "gold_evidence_recall_at_10": 1.0,
                        "MRR": 1.0,
                    }
                ],
                "groundedness_metrics": {"Unsupported Claim Rate": 0.0},
                "performance_ms": {"total_rag_ms": {"p50": 10.0, "p95": 10.0}},
                "context_metrics": {"Context Tokens": 12},
                "official_qasper": {},
            }
        ),
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": directory.name,
                "git_sha": "abc123",
                "status": "complete",
                "error_count": 0,
                "dataset": "qasper",
                "dataset_version": "0.3",
                "split": "validation",
                "source_path": str(source_path),
                "source_sha256": source_sha256,
                "sample_hash": "sample-sha",
                "question_count": 1,
                "paper_count": 1,
                "selected_question_ids": [question_id],
                "answer_generation": True,
                "qrels_path": str(qrels_path),
                "files": {
                    "predictions": "predictions.jsonl",
                    "retrieval_trace": "retrieval_trace.jsonl",
                    "errors": "errors.jsonl",
                    "metrics": "metrics.json",
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_audit_accepts_complete_real_provider_run_and_rejects_wrong_paper(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "run", source_path=source)

    assert audit_qasper_run(run)["ok"] is True

    invalid = _write_run(
        tmp_path / "wrong-paper",
        source_path=source,
        final_document_id="qasper:validation:p2",
    )
    report = audit_qasper_run(invalid)
    assert report["ok"] is False
    assert any("out-of-scope" in issue for issue in report["issues"])


def test_strict_comparison_is_zero_on_self_and_rejects_different_samples(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    baseline = _write_run(tmp_path / "baseline", source_path=source)
    candidate = _write_run(
        tmp_path / "candidate",
        source_path=source,
        answer_f1=0.75,
    )

    result = compare_qasper_runs(baseline, baseline, resamples=100)
    assert result["question_count"] == 1
    assert all(metric["delta"] == 0 for metric in result["metrics"].values())
    improved = compare_qasper_runs(baseline, candidate, resamples=100)
    assert improved["metrics"]["Answer F1"]["delta"] == pytest.approx(0.25)

    other_sample = _write_run(
        tmp_path / "other-sample",
        source_path=source,
        question_id="q2",
    )
    with pytest.raises(ValueError, match="qrels SHA256"):
        compare_qasper_runs(baseline, other_sample, resamples=100)

    different_source = tmp_path / "other-source.json"
    different_source.write_text("{\"different\": true}", encoding="utf-8")
    other_candidate = _write_run(
        tmp_path / "different-source",
        source_path=different_source,
    )
    with pytest.raises(ValueError, match="source data SHA256"):
        compare_qasper_runs(baseline, other_candidate, resamples=100)
