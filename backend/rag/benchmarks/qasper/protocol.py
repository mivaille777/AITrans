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


def _mapped_gold_evidence(case: dict[str, Any], label: str) -> bool:
    mapped = case.get("mapped_gold_evidence")
    if isinstance(mapped, bool):
        return mapped
    relevant_chunk_count = case.get("relevant_chunk_count")
    if (
        isinstance(relevant_chunk_count, (int, float))
        and not isinstance(relevant_chunk_count, bool)
        and math.isfinite(float(relevant_chunk_count))
        and relevant_chunk_count >= 0
    ):
        return relevant_chunk_count > 0
    raise TypeError(f"{label} mapped_gold_evidence is missing or invalid")


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
    verification_fallback_count = 0
    policy_abstention_count = 0
    dense_record_count = 0
    sparse_record_count = 0
    reranker_record_count = 0
    scoped_candidate_count = 0
    retrieval_candidate_count = 0
    selected_evidence_count = 0
    invalid_selected_evidence_offset_count = 0
    out_of_scope_candidates: list[str] = []
    out_of_scope_retrieval_candidates: list[str] = []
    invalid_selected_evidence_offsets: list[str] = []
    missing_answers: list[str] = []
    invalid_answer_contracts: list[str] = []
    invalid_answer_contract_citations: list[str] = []
    answer_contract_parse_fallbacks: list[str] = []
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
        final_candidates = trace.get("final_candidates", [])
        if not isinstance(final_candidates, list):
            final_candidates = []
        candidate_pool = trace.get("retrieval_candidate_pool", final_candidates)
        if not isinstance(candidate_pool, list):
            candidate_pool = final_candidates
        candidate_pool_by_id: dict[str, dict[str, Any]] = {}
        for candidate in candidate_pool:
            if not isinstance(candidate, dict):
                continue
            retrieval_candidate_count += 1
            candidate_id = str(candidate.get("chunk_id", ""))
            if candidate_id:
                candidate_pool_by_id[candidate_id] = candidate
            if str(candidate.get("document_id", "")) != expected_document_id:
                out_of_scope_retrieval_candidates.append(question_id)
        pool_chunk_ids = [
            str(candidate.get("chunk_id", ""))
            for candidate in candidate_pool
            if isinstance(candidate, dict) and candidate.get("chunk_id")
        ]
        final_chunk_ids = [
            str(candidate.get("chunk_id", ""))
            for candidate in final_candidates
            if isinstance(candidate, dict) and candidate.get("chunk_id")
        ]
        if "retrieval_candidate_pool" in trace:
            if len(pool_chunk_ids) != len(set(pool_chunk_ids)):
                issues.append(f"{question_id}: retrieval candidate pool contains duplicate chunk IDs")
            selected_span_keys: list[tuple[str, int, int] | tuple[str]] = []
            for candidate in final_candidates:
                if not isinstance(candidate, dict):
                    continue
                candidate_id = str(candidate.get("chunk_id", ""))
                candidate_metadata = candidate.get("metadata", {})
                selection = (
                    candidate_metadata.get("evidence_selection", {})
                    if isinstance(candidate_metadata, dict)
                    else {}
                )
                start_offset = selection.get("start_offset") if isinstance(selection, dict) else None
                end_offset = selection.get("end_offset") if isinstance(selection, dict) else None
                source_chunk_id = str(
                    selection.get("source_chunk_id", candidate_id)
                    if isinstance(selection, dict)
                    else candidate_id
                )
                if (
                    isinstance(start_offset, int)
                    and not isinstance(start_offset, bool)
                    and isinstance(end_offset, int)
                    and not isinstance(end_offset, bool)
                ):
                    selected_span_keys.append((source_chunk_id, start_offset, end_offset))
                else:
                    selected_span_keys.append((candidate_id,))
            if len(selected_span_keys) != len(set(selected_span_keys)):
                issues.append(f"{question_id}: selected evidence contains duplicate spans")
            if set(final_chunk_ids).difference(pool_chunk_ids):
                issues.append(f"{question_id}: selected evidence is absent from the retrieval pool")
            predicted_pool_ids = prediction.get("retrieved_chunk_ids")
            if predicted_pool_ids != pool_chunk_ids:
                issues.append(f"{question_id}: prediction retrieval IDs do not match the trace pool")
            predicted_selected_ids = prediction.get("selected_evidence_chunk_ids")
            if predicted_selected_ids != final_chunk_ids:
                issues.append(f"{question_id}: prediction selected evidence does not match final candidates")
            predicted_paragraph_ids = prediction.get("predicted_evidence_paragraph_ids")
            selected_paragraph_ids = list(
                dict.fromkeys(
                    str(paragraph_id)
                    for candidate in final_candidates
                    if isinstance(candidate, dict)
                    for paragraph_id in candidate.get("source_paragraph_ids", [])
                    if str(paragraph_id)
                )
            )
            if predicted_paragraph_ids != selected_paragraph_ids:
                issues.append(f"{question_id}: predicted evidence paragraphs do not match selected candidates")
            profile = manifest.get("quality_profile")
            if isinstance(profile, dict):
                pool_limit = profile.get("candidate_pool_size")
                if isinstance(pool_limit, int) and len(pool_chunk_ids) > pool_limit:
                    issues.append(f"{question_id}: retrieval candidate pool exceeds its profile limit")
                variant_id = str(manifest.get("evidence_selection_variant", ""))
                top_k_by_variant = profile.get("selected_top_k_by_variant", {})
                if isinstance(top_k_by_variant, dict):
                    selected_limit = top_k_by_variant.get(variant_id)
                    if isinstance(selected_limit, int) and len(final_chunk_ids) > selected_limit:
                        issues.append(f"{question_id}: selected evidence exceeds its profile Top-K")
                if variant_id == "evidence_selection":
                    maximum_excerpt_tokens = profile.get("maximum_excerpt_tokens")
                    selection_metadata = (
                        retrieval_metadata.get("evidence_selection", {})
                        if isinstance(retrieval_metadata, dict)
                        else {}
                    )
                    if isinstance(selection_metadata, dict):
                        no_valid_excerpt = selection_metadata.get("no_valid_excerpt")
                        if not isinstance(no_valid_excerpt, bool):
                            issues.append(f"{question_id}: evidence selection is missing no_valid_excerpt status")
                        fallback_count = selection_metadata.get("fallback_count", 0)
                        no_valid_excerpt_count = selection_metadata.get(
                            "no_valid_excerpt_count", 0
                        )
                        if (
                            isinstance(fallback_count, bool)
                            or not isinstance(fallback_count, int)
                            or fallback_count < 0
                            or isinstance(no_valid_excerpt_count, bool)
                            or not isinstance(no_valid_excerpt_count, int)
                            or no_valid_excerpt_count < 0
                        ):
                            issues.append(f"{question_id}: evidence selection fallback counts are invalid")
                        elif no_valid_excerpt and final_candidates:
                            fallback_enabled = bool(
                                profile.get(
                                    "fallback_to_source_chunk_for_multi_paragraph_coverage",
                                    False,
                                )
                            )
                            if (
                                not fallback_enabled
                                or fallback_count < no_valid_excerpt_count
                                or no_valid_excerpt_count == 0
                            ):
                                issues.append(f"{question_id}: invalid excerpts entered selected evidence without controlled fallback")
                    for candidate in final_candidates:
                        if not isinstance(candidate, dict):
                            continue
                        candidate_metadata = candidate.get("metadata", {})
                        evidence_selection = (
                            candidate_metadata.get("evidence_selection", {})
                            if isinstance(candidate_metadata, dict)
                            else {}
                        )
                        is_fallback = (
                            isinstance(evidence_selection, dict)
                            and evidence_selection.get("fallback_applied") is True
                        )
                        has_source_offsets = (
                            isinstance(evidence_selection, dict)
                            and isinstance(evidence_selection.get("start_offset"), int)
                            and isinstance(evidence_selection.get("end_offset"), int)
                        )
                        if (
                            has_source_offsets
                            and not is_fallback
                            and isinstance(maximum_excerpt_tokens, int)
                            and int(candidate.get("token_count", 0) or 0)
                            > maximum_excerpt_tokens
                        ):
                            issues.append(f"{question_id}: selected excerpt exceeds its token limit")
        selected_evidence = trace.get("selected_evidence")
        if isinstance(selected_evidence, list):
            selected_evidence_count += len(selected_evidence)
        else:
            selected_evidence_count += len(final_candidates)
        for candidate in final_candidates:
            if not isinstance(candidate, dict):
                continue
            scoped_candidate_count += 1
            if str(candidate.get("document_id", "")) != expected_document_id:
                out_of_scope_candidates.append(question_id)
            candidate_metadata = candidate.get("metadata", {})
            selection = (
                candidate_metadata.get("evidence_selection", {})
                if isinstance(candidate_metadata, dict)
                else {}
            )
            if (
                isinstance(selection, dict)
                and selection.get("source_chunk_id")
                and selection.get("fallback_applied") is not True
            ):
                source_id = str(selection.get("source_chunk_id", ""))
                source_candidate = candidate_pool_by_id.get(source_id)
                source_text = (
                    str(source_candidate.get("text", ""))
                    if source_candidate is not None
                    else ""
                )
                start_offset = selection.get("start_offset")
                end_offset = selection.get("end_offset")
                selected_text = str(candidate.get("text", ""))
                offset_valid = (
                    isinstance(start_offset, int)
                    and not isinstance(start_offset, bool)
                    and isinstance(end_offset, int)
                    and not isinstance(end_offset, bool)
                    and 0 <= start_offset < end_offset <= len(source_text)
                    and source_candidate is not None
                    and source_text[start_offset:end_offset] == selected_text
                )
                if not offset_valid:
                    invalid_selected_evidence_offsets.append(question_id)
        if manifest.get("answer_generation"):
            answer_generation = prediction.get("answer_generation", {})
            provider = str(answer_generation.get("provider", "")).strip().casefold()
            answer_metadata = answer_generation.get("metadata", {})
            if not isinstance(answer_metadata, dict):
                answer_metadata = {}
            if answer_metadata.get("fallback_applied") is True:
                verification_fallback_count += 1
                configured_answer_model = manifest.get("answer_model", {})
                actual_provider = (
                    str(configured_answer_model.get("provider", "")).strip().casefold()
                    if isinstance(configured_answer_model, dict)
                    else ""
                )
                if actual_provider:
                    provider_counts[actual_provider] += 1
                else:
                    missing_answers.append(question_id)
            elif answer_metadata.get("abstained") is True and str(
                answer_metadata.get("reason", "")
            ).strip():
                policy_abstention_count += 1
            elif provider and provider != "policy":
                provider_counts[provider] += 1
            else:
                missing_answers.append(question_id)
        answer_contract = manifest.get("answer_contract")
        if isinstance(answer_contract, dict):
            answer_generation = prediction.get("answer_generation", {})
            answer_metadata = (
                answer_generation.get("metadata", {})
                if isinstance(answer_generation, dict)
                else {}
            )
            if not isinstance(answer_metadata, dict):
                answer_metadata = {}
            contract_status = answer_metadata.get("answer_contract_status")
            if contract_status == "invalid_format_fallback":
                safe_fallback = (
                    bool(str(answer_metadata.get("answer_contract_parse_error", "")).strip())
                    and prediction.get("answer") == "Unanswerable"
                    and prediction.get("user_visible_answer") == "Unanswerable"
                    and answer_metadata.get("direct_answer") == "Unanswerable"
                )
                if safe_fallback:
                    answer_contract_parse_fallbacks.append(question_id)
                else:
                    invalid_answer_contracts.append(question_id)
            elif contract_status not in {"valid", "not_invoked"}:
                invalid_answer_contracts.append(question_id)
            elif contract_status == "valid":
                if answer_metadata.get("answer_contract_citation_validation_passed") is not True:
                    invalid_answer_contract_citations.append(question_id)
                if answer_metadata.get("direct_answer") != prediction.get("answer"):
                    issues.append(
                        f"{question_id}: official answer differs from the validated direct answer"
                    )
                if answer_metadata.get("user_visible_final_output") != prediction.get(
                    "user_visible_answer"
                ):
                    issues.append(
                        f"{question_id}: visible answer differs from the validated contract output"
                    )
    if out_of_scope_candidates:
        issues.append(f"out-of-scope final candidates: {sorted(set(out_of_scope_candidates))[:10]}")
    if out_of_scope_retrieval_candidates:
        issues.append(
            "out-of-scope retrieval candidates: "
            + str(sorted(set(out_of_scope_retrieval_candidates))[:10])
        )
    invalid_selected_evidence_offset_count = len(invalid_selected_evidence_offsets)
    if invalid_selected_evidence_offsets:
        issues.append(
            "selected excerpts are not exact source spans for questions: "
            + str(sorted(set(invalid_selected_evidence_offsets))[:10])
        )
    if expected_count and (not dense_record_count or not sparse_record_count or not reranker_record_count):
        issues.append("dense, BM25, and reranker retrieval stages must be recorded")
    if require_answer_generation and not manifest.get("answer_generation"):
        issues.append("run used retrieval-only mode; answer generation is required")
    if missing_answers:
        issues.append(f"missing answer provider record for questions: {missing_answers[:10]}")
    if invalid_answer_contracts:
        issues.append(
            "answer contract was invalid or missing for questions: "
            + str(sorted(set(invalid_answer_contracts))[:10])
        )
    if invalid_answer_contract_citations:
        issues.append(
            "answer contract citations failed validation for questions: "
            + str(sorted(set(invalid_answer_contract_citations))[:10])
        )

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
        "retrieval_candidate_count": retrieval_candidate_count,
        "selected_evidence_count": selected_evidence_count,
        "invalid_selected_evidence_offset_count": invalid_selected_evidence_offset_count,
        "answer_generation": bool(manifest.get("answer_generation")),
        "answer_provider_counts": dict(sorted(provider_counts.items())),
        "verification_fallback_count": verification_fallback_count,
        "policy_abstention_count": policy_abstention_count,
        "answer_contract": manifest.get("answer_contract"),
        "answer_contract_invalid_count": len(set(invalid_answer_contracts)),
        "answer_contract_invalid_citation_count": len(
            set(invalid_answer_contract_citations)
        ),
        "answer_contract_parse_fallback_count": len(
            set(answer_contract_parse_fallbacks)
        ),
        "answer_contract_parse_fallback_question_ids": sorted(
            set(answer_contract_parse_fallbacks)
        ),
        "unsupported_claim_rate": groundedness.get("Unsupported Claim Rate"),
        "performance_ms": performance,
        "context_metrics": metrics.get("context_metrics", {}),
        "official_qasper": metrics.get("official_qasper", {}),
        "answer_behavior": metrics.get("answer_behavior", {}),
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
    metric_fields = ("official_answer_f1", "official_evidence_f1", "MRR")
    for label, cases in (("baseline", baseline_by_id), ("candidate", candidate_by_id)):
        for question_id, case in cases.items():
            _mapped_gold_evidence(case, f"{label} {question_id}")
            for field in metric_fields:
                value = case.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{label} metric {field} is missing or invalid for {question_id}")
            recall_value = case.get("candidate_gold_evidence_recall_at_10")
            if recall_value is None:
                recall_value = case.get("gold_evidence_recall_at_10")
            if (
                isinstance(recall_value, bool)
                or not isinstance(recall_value, (int, float))
                or not math.isfinite(float(recall_value))
            ):
                raise ValueError(
                    f"{label} candidate Gold Evidence Recall@10 is missing or invalid for {question_id}"
                )
    for question_id in expected_ids:
        if _mapped_gold_evidence(
            baseline_by_id[question_id], f"baseline {question_id}"
        ) != _mapped_gold_evidence(
            candidate_by_id[question_id], f"candidate {question_id}"
        ):
            raise ValueError(
                f"runs disagree on mapped_gold_evidence for {question_id}"
            )
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
