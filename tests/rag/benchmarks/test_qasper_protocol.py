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
                        "mapped_gold_evidence": True,
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
                "answer_model": {"provider": "deepseek", "model": "test"},
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


def test_audit_counts_provider_call_before_verification_fallback(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "fallback", source_path=source)
    prediction_path = run / "predictions.jsonl"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["answer_generation"] = {
        "provider": "policy",
        "model": "grounding-verification-fallback",
        "metadata": {"fallback_applied": True, "verification_passed": False},
    }
    prediction_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    report = audit_qasper_run(run)

    assert report["ok"] is True
    assert report["answer_provider_counts"] == {"deepseek": 1}
    assert report["verification_fallback_count"] == 1


def test_audit_accepts_explicit_policy_abstention_without_provider_call(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "abstention", source_path=source)
    prediction_path = run / "predictions.jsonl"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["answer"] = "Unanswerable"
    prediction["answer_generation"] = {
        "provider": "policy",
        "model": "insufficient-evidence",
        "metadata": {"abstained": True, "reason": "no_retrieved_evidence"},
    }
    prediction_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    report = audit_qasper_run(run)

    assert report["ok"] is True
    assert report["answer_provider_counts"] == {}
    assert report["policy_abstention_count"] == 1


def test_audit_accepts_contract_parse_failure_only_with_safe_abstention(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "contract-fallback", source_path=source)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["answer_contract"] = {"contract_id": "test-v1", "version": 1}
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    prediction_path = run / "predictions.jsonl"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction["answer"] = "Unanswerable"
    prediction["user_visible_answer"] = "Unanswerable"
    prediction["answer_generation"]["metadata"] = {
        "answer_contract_status": "invalid_format_fallback",
        "answer_contract_parse_error": "missing required field",
        "direct_answer": "Unanswerable",
        "user_visible_final_output": "Unanswerable",
    }
    prediction_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    report = audit_qasper_run(run)

    assert report["ok"] is True
    assert report["answer_contract_parse_fallback_count"] == 1

    prediction["user_visible_answer"] = "Unsupported generated claim"
    prediction["answer_generation"]["metadata"]["user_visible_final_output"] = (
        "Unsupported generated claim"
    )
    prediction_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")
    unsafe_report = audit_qasper_run(run)
    assert unsafe_report["ok"] is False
    assert unsafe_report["answer_contract_invalid_count"] == 1


def test_audit_rejects_selected_excerpt_with_invalid_source_offset(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "invalid-offset", source_path=source)
    trace_path = run / "retrieval_trace.jsonl"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["retrieval_candidate_pool"] = [
        {
            "chunk_id": "chunk-1",
            "document_id": "qasper:validation:p1",
            "text": "source text",
        }
    ]
    trace["final_candidates"][0].update(
        {
            "text": "wrong span",
            "metadata": {
                "evidence_selection": {
                    "source_chunk_id": "chunk-1",
                    "start_offset": 0,
                    "end_offset": 6,
                }
            },
        }
    )
    trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")

    report = audit_qasper_run(run)

    assert report["ok"] is False
    assert report["invalid_selected_evidence_offset_count"] == 1
    assert any("exact source spans" in issue for issue in report["issues"])


def test_audit_accepts_distinct_selected_spans_from_one_source_chunk(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    run = _write_run(tmp_path / "multiple-spans", source_path=source)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "evidence_selection_variant": "evidence_selection",
            "quality_profile": {
                "candidate_pool_size": 20,
                "selected_top_k_by_variant": {"evidence_selection": 5},
                "maximum_excerpt_tokens": 180,
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    prediction_path = run / "predictions.jsonl"
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    prediction.update(
        {
            "retrieved_chunk_ids": ["chunk-1"],
            "selected_evidence_chunk_ids": ["chunk-1", "chunk-1"],
            "predicted_evidence_paragraph_ids": ["paragraph-1"],
        }
    )
    prediction_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    trace_path = run / "retrieval_trace.jsonl"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["retrieval_candidate_pool"] = [
        {
            "chunk_id": "chunk-1",
            "document_id": "qasper:validation:p1",
            "text": "first second",
        }
    ]
    trace["retrieval_metadata"]["evidence_selection"] = {
        "no_valid_excerpt": False,
    }
    trace["final_candidates"] = [
        {
            "chunk_id": "chunk-1",
            "document_id": "qasper:validation:p1",
            "text": "first",
            "token_count": 1,
            "source_paragraph_ids": ["paragraph-1"],
            "metadata": {
                "evidence_selection": {
                    "source_chunk_id": "chunk-1",
                    "start_offset": 0,
                    "end_offset": 5,
                }
            },
        },
        {
            "chunk_id": "chunk-1",
            "document_id": "qasper:validation:p1",
            "text": "second",
            "token_count": 1,
            "source_paragraph_ids": ["paragraph-1"],
            "metadata": {
                "evidence_selection": {
                    "source_chunk_id": "chunk-1",
                    "start_offset": 6,
                    "end_offset": 12,
                }
            },
        },
    ]
    trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")

    report = audit_qasper_run(run)

    assert report["ok"] is True
    assert report["invalid_selected_evidence_offset_count"] == 0


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
