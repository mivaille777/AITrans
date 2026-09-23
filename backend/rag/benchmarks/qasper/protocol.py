from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.rag.benchmarks.qasper.statistics import paired_bootstrap


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"expected JSON object at {path}:{line_number}")
            records.append(value)
    return records


def _unique_by_id(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = str(record.get("question_id", "")).strip()
        if not question_id:
            raise ValueError(f"{label} contains a record without question_id")
        if question_id in result:
            raise ValueError(f"{label} contains duplicate question_id {question_id}")
        result[question_id] = record
    return result


def _resolve_qrels_path(manifest: dict[str, Any], run_directory: Path) -> Path:
    raw_path = Path(str(manifest.get("qrels_path", ""))).expanduser()
    if not str(raw_path):
        raise ValueError("manifest is missing qrels_path")
    if not raw_path.is_absolute():
        raw_path = run_directory / raw_path
    return raw_path.resolve()


def audit_qasper_run(
    run_directory: str | Path,
    *,
    require_answer_generation: bool = True,
    verify_source: bool = True,
) -> dict[str, Any]:
    """Validate run artifacts, sample identity, provider execution, and paper scope."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest_path = run_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"QASPER run manifest not found: {manifest_path}")
    manifest = _read_json(manifest_path)
    issues: list[str] = []
    if manifest.get("status") != "complete":
        issues.append(f"manifest status is {manifest.get('status')!r}, expected 'complete'")
    if int(manifest.get("error_count", 0) or 0) != 0:
        issues.append(f"manifest error_count is {manifest.get('error_count')!r}")

    file_names = manifest.get("files", {})
    paths = {
        "predictions": run_path / str(file_names.get("predictions", "predictions.jsonl")),
        "traces": run_path / str(file_names.get("retrieval_trace", "retrieval_trace.jsonl")),
        "errors": run_path / str(file_names.get("errors", "errors.jsonl")),
        "metrics": run_path / str(file_names.get("metrics", "metrics.json")),
        "qrels": _resolve_qrels_path(manifest, run_path),
    }
    for label, path in paths.items():
        if not path.is_file():
            issues.append(f"missing {label} file: {path}")
    if any(not paths[key].is_file() for key in ("predictions", "traces", "errors", "metrics", "qrels")):
        return {"run_directory": str(run_path), "ok": False, "issues": issues}

    if verify_source:
        source_path = Path(str(manifest.get("source_path", ""))).expanduser()
        if not source_path.is_file():
            issues.append(f"source data file is missing: {source_path}")
        else:
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source_hash != manifest.get("source_sha256"):
                issues.append("source data SHA256 does not match the run manifest")

    qrels = _unique_by_id(_read_jsonl(paths["qrels"]), "qrels")
    predictions = _unique_by_id(_read_jsonl(paths["predictions"]), "predictions")
    traces = _unique_by_id(_read_jsonl(paths["traces"]), "traces")
    expected_ids_raw = manifest.get("selected_question_ids")
    if not isinstance(expected_ids_raw, list) or not expected_ids_raw:
        issues.append("manifest selected_question_ids is missing or empty")
        expected_ids: set[str] = set()
    else:
        normalized_expected_ids = [str(value).strip() for value in expected_ids_raw]
        if any(not value for value in normalized_expected_ids):
            issues.append("manifest selected_question_ids contains an empty ID")
        if len(set(normalized_expected_ids)) != len(normalized_expected_ids):
            issues.append("manifest selected_question_ids contains duplicates")
        expected_ids = set(normalized_expected_ids)

    id_sets = {
        "qrels": set(qrels),
        "predictions": set(predictions),
        "traces": set(traces),
        "manifest": expected_ids,
    }
    for label, ids in id_sets.items():
        if ids != expected_ids:
            missing = sorted(expected_ids - ids)
            extra = sorted(ids - expected_ids)
            issues.append(
                f"{label} question IDs mismatch; missing={missing[:10]}, extra={extra[:10]}"
            )

    expected_count = len(expected_ids)
    if int(manifest.get("question_count", -1)) != expected_count:
        issues.append("manifest question_count does not match selected_question_ids")
    metrics = _read_json(paths["metrics"])
    for label, value in (
        ("metrics question_count", metrics.get("question_count")),
        ("metrics prediction_count", metrics.get("prediction_count")),
        ("metrics trace_count", metrics.get("trace_count")),
    ):
        if value != expected_count:
            issues.append(f"{label} is {value!r}, expected {expected_count}")

    if paths["errors"].stat().st_size != 0:
        issues.append("errors.jsonl is not empty")

    question_id_selection = manifest.get("question_id_selection")
    if isinstance(question_id_selection, dict):
        ordered_id_payload = "\n".join(str(value) for value in expected_ids_raw) + "\n"
        ordered_ids_hash = hashlib.sha256(ordered_id_payload.encode("utf-8")).hexdigest()
        if question_id_selection.get("question_ids_sha256") != ordered_ids_hash:
            issues.append("selected question ID SHA256 does not match manifest IDs")

    provider_counts: Counter[str] = Counter()
    dense_record_count = 0
    sparse_record_count = 0
    reranker_record_count = 0
    scoped_candidate_count = 0
    out_of_scope_candidates: list[str] = []
    missing_answers: list[str] = []
    for question_id in sorted(expected_ids):
        qrel = qrels.get(question_id, {})
        prediction = predictions.get(question_id, {})
        trace = traces.get(question_id, {})
        paper_id = str(qrel.get("paper_id", ""))
        expected_document_id = f"qasper:{manifest.get('split', '')}:{paper_id}"
        trace_scope = str(trace.get("scope_document_id", ""))
        if not paper_id or trace_scope != expected_document_id:
            issues.append(f"{question_id}: trace paper scope is {trace_scope!r}, expected {expected_document_id!r}")
        retrieval_metadata = trace.get("retrieval_metadata", {})
        if isinstance(retrieval_metadata, dict):
            dense_record_count += int(retrieval_metadata.get("dense_count", 0) or 0) > 0
            sparse_record_count += int(retrieval_metadata.get("sparse_count", 0) or 0) > 0
            reranker_record_count += bool(retrieval_metadata.get("reranker_applied"))
        for candidate in trace.get("final_candidates", []):
            if not isinstance(candidate, dict):
                continue
            scoped_candidate_count += 1
            if str(candidate.get("document_id", "")) != expected_document_id:
                out_of_scope_candidates.append(question_id)
        if manifest.get("answer_generation"):
            answer_generation = prediction.get("answer_generation", {})
            provider = str(answer_generation.get("provider", "")).strip().casefold()
            if provider:
                provider_counts[provider] += 1
            else:
                missing_answers.append(question_id)
    if out_of_scope_candidates:
        issues.append(f"out-of-scope final candidates: {sorted(set(out_of_scope_candidates))[:10]}")
    if expected_count and (not dense_record_count or not sparse_record_count or not reranker_record_count):
        issues.append("dense, BM25, and reranker retrieval stages must be recorded")
    if require_answer_generation and not manifest.get("answer_generation"):
        issues.append("run used retrieval-only mode; answer generation is required")
    if missing_answers:
        issues.append(f"missing answer provider record for questions: {missing_answers[:10]}")

    groundedness = metrics.get("groundedness_metrics", {})
    performance = metrics.get("performance_ms", {})
    result = {
        "run_id": manifest.get("run_id", run_path.name),
        "run_directory": str(run_path),
        "ok": not issues,
        "issues": issues,
        "source_sha256": manifest.get("source_sha256"),
        "sample_hash": manifest.get("sample_hash"),
        "qrels_sha256": hashlib.sha256(paths["qrels"].read_bytes()).hexdigest(),
        "question_count": expected_count,
        "question_ids": sorted(expected_ids),
        "paper_count": manifest.get("paper_count"),
        "error_count": manifest.get("error_count", 0),
        "dense_question_count": int(dense_record_count),
        "bm25_question_count": int(sparse_record_count),
        "reranked_question_count": int(reranker_record_count),
        "scoped_candidate_count": scoped_candidate_count,
        "answer_generation": bool(manifest.get("answer_generation")),
        "answer_provider_counts": dict(sorted(provider_counts.items())),
        "unsupported_claim_rate": groundedness.get("Unsupported Claim Rate"),
        "performance_ms": performance,
        "context_metrics": metrics.get("context_metrics", {}),
        "official_qasper": metrics.get("official_qasper", {}),
        "quality_stratification": metrics.get("quality_stratification", {}),
    }
    return result


def compare_qasper_runs(
    baseline_directory: str | Path,
    candidate_directory: str | Path,
    *,
    seed: int = 42,
    resamples: int = 5000,
) -> dict[str, Any]:
    """Compare two completed QASPER runs after strict paired-set validation."""

    baseline_path = Path(baseline_directory).expanduser().resolve()
    candidate_path = Path(candidate_directory).expanduser().resolve()
    baseline_audit = audit_qasper_run(baseline_path, require_answer_generation=False)
    candidate_audit = audit_qasper_run(candidate_path, require_answer_generation=False)
    for label, audit in (("baseline", baseline_audit), ("candidate", candidate_audit)):
        if not audit["ok"]:
            raise ValueError(f"{label} run failed audit: " + "; ".join(audit["issues"]))
    for field, label in (
        ("source_sha256", "source data SHA256"),
        ("qrels_sha256", "qrels SHA256"),
        ("question_ids", "selected question IDs"),
    ):
        if baseline_audit[field] != candidate_audit[field]:
            if field == "question_ids":
                left = set(baseline_audit[field])
                right = set(candidate_audit[field])
                difference = {
                    "baseline_only": sorted(left - right),
                    "candidate_only": sorted(right - left),
                }
                detail = json.dumps(difference, ensure_ascii=False)
            else:
                detail = f"baseline={baseline_audit[field]!r}, candidate={candidate_audit[field]!r}"
            raise ValueError(f"runs have different {label}: {detail}")

    baseline_metrics = _read_json(baseline_path / "metrics.json")
    candidate_metrics = _read_json(candidate_path / "metrics.json")
    baseline_cases = baseline_metrics.get("per_question", [])
    candidate_cases = candidate_metrics.get("per_question", [])
    if not isinstance(baseline_cases, list) or not isinstance(candidate_cases, list):
        raise TypeError("metrics.json must include per_question arrays")
    baseline_by_id = _unique_by_id(baseline_cases, "baseline per_question metrics")
    candidate_by_id = _unique_by_id(candidate_cases, "candidate per_question metrics")
    expected_ids = set(baseline_audit["question_ids"])
    if set(baseline_by_id) != expected_ids or set(candidate_by_id) != expected_ids:
        raise ValueError("per_question metric IDs must exactly match the audited qrels IDs")
    metric_fields = (
        "official_answer_f1",
        "official_evidence_f1",
        "gold_evidence_recall_at_10",
        "MRR",
    )
    for label, cases in (("baseline", baseline_by_id), ("candidate", candidate_by_id)):
        for question_id, case in cases.items():
            for field in metric_fields:
                value = case.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{label} metric {field} is missing or invalid for {question_id}")
    bootstrap = paired_bootstrap(
        baseline_cases,
        candidate_cases,
        seed=seed,
        resamples=resamples,
    )
    return {
        "comparison_version": 1,
        "baseline_run_id": baseline_audit["run_id"],
        "candidate_run_id": candidate_audit["run_id"],
        "baseline_directory": str(baseline_path),
        "candidate_directory": str(candidate_path),
        "source_sha256": baseline_audit["source_sha256"],
        "qrels_sha256": baseline_audit["qrels_sha256"],
        "question_count": len(expected_ids),
        "question_ids_sha256": hashlib.sha256(
            ("\n".join(sorted(expected_ids)) + "\n").encode("utf-8")
        ).hexdigest(),
        "seed": seed,
        "resamples": resamples,
        "metrics": bootstrap["metrics"],
    }


def write_comparison_report(
    comparison: dict[str, Any],
    candidate_directory: str | Path,
) -> Path:
    candidate_path = Path(candidate_directory).expanduser().resolve()
    report_directory = candidate_path / "comparison"
    report_directory.mkdir(parents=True, exist_ok=True)
    safe_baseline = re.sub(r"[^A-Za-z0-9._-]", "-", str(comparison["baseline_run_id"]))
    safe_candidate = re.sub(r"[^A-Za-z0-9._-]", "-", str(comparison["candidate_run_id"]))
    path = report_directory / f"{safe_baseline}-vs-{safe_candidate}.json"
    path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = ["audit_qasper_run", "compare_qasper_runs", "write_comparison_report"]
