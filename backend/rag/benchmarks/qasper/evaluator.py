from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from backend.rag.benchmarks.common import atomic_write_json, benchmark_root
from backend.rag.evaluation import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from backend.rag.sparse.store import BM25SparseRetriever
from third_party.qasper import official_evaluator

EVALUATION_KS = (5, 8, 10, 20)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise TypeError(f"JSONL record {line_number} in {path} must be an object")
        records.append(record)
    return records


def _by_question_id(
    records: Iterable[dict[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = str(record.get("question_id", "")).strip()
        if not question_id:
            raise ValueError(f"{label} record has no question_id")
        if question_id in result:
            raise ValueError(f"duplicate {label} question_id: {question_id}")
        result[question_id] = record
    return result


def _references(qrel: dict[str, Any]) -> list[dict[str, Any]]:
    answers = qrel.get("answers", [])
    if not isinstance(answers, list):
        raise TypeError("qrels answers must be a list")
    return [answer for answer in answers if isinstance(answer, dict)]


def _gold_paragraph_sets(qrel: dict[str, Any]) -> list[set[str]]:
    return [
        {
            str(paragraph_id)
            for paragraph_id in answer.get("evidence_paragraph_ids", [])
            if str(paragraph_id)
        }
        for answer in _references(qrel)
        if answer.get("evidence_paragraph_ids")
    ]


def _gold_chunk_sets(
    qrel: dict[str, Any],
    paragraph_to_chunks: dict[str, tuple[str, ...]],
) -> list[set[str]]:
    return [
        {
            chunk_id
            for paragraph_id in paragraph_ids
            for chunk_id in paragraph_to_chunks.get(paragraph_id, ())
        }
        for paragraph_ids in _gold_paragraph_sets(qrel)
    ]


def _top_candidate_paragraphs(
    candidates: Sequence[dict[str, Any]],
    *,
    limit: int,
) -> set[str]:
    paragraph_ids: set[str] = set()
    for candidate in candidates[:limit]:
        values = candidate.get("source_paragraph_ids", [])
        if isinstance(values, list):
            paragraph_ids.update(str(value) for value in values if str(value))
    return paragraph_ids


def _paragraph_precision_recall_f1(
    predicted: set[str],
    references: Sequence[set[str]],
) -> tuple[float, float, float]:
    if not references:
        return 0.0, 0.0, 0.0
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    f1_scores: list[float] = []
    for gold in references:
        overlap = len(predicted.intersection(gold))
        precision = overlap / len(predicted) if predicted else 0.0
        recall = overlap / len(gold) if gold else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        precision_scores.append(precision)
        recall_scores.append(recall)
        f1_scores.append(f1)
    return max(precision_scores), max(recall_scores), max(f1_scores)


def _best_paragraph_coverage(
    predicted: set[str],
    references: Sequence[set[str]],
) -> float:
    return max(
        (
            len(predicted.intersection(gold)) / len(gold)
            for gold in references
            if gold
        ),
        default=0.0,
    )


def _gold_sufficient(
    context_paragraph_ids: set[str],
    references: Sequence[set[str]],
) -> bool:
    return any(
        bool(gold) and gold.issubset(context_paragraph_ids)
        for gold in references
    )


def _is_unanswerable_answer(answer: str) -> bool:
    normalized = unicodedata.normalize("NFKC", answer).casefold().strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return normalized in {
        "unanswerable",
        "no answer",
        "not answerable",
        "cannot be answered",
        "insufficient information",
        "unknown",
    }


def _answer_behavior_metrics(
    qrels: dict[str, dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    *,
    contract_enabled: bool,
) -> dict[str, Any]:
    answerable_count = 0
    unanswerable_count = 0
    false_abstentions = 0
    missed_abstentions = 0
    boolean_count = 0
    boolean_answerable_count = 0
    boolean_correct = 0
    contract_response_count = 0
    contract_valid_count = 0
    citation_valid_count = 0
    model_abstention_count = 0
    answer_token_estimates: list[float] = []
    visible_token_estimates: list[float] = []

    for question_id, qrel in qrels.items():
        prediction = predictions.get(question_id, {})
        answer = str(prediction.get("answer", "") or "")
        generation = prediction.get("answer_generation", {})
        details = generation.get("metadata", {}) if isinstance(generation, dict) else {}
        if not isinstance(details, dict):
            details = {}
        gold_unanswerable = bool(qrel.get("no_answer"))
        predicted_unanswerable = (
            str(details.get("answer_contract_answer_type", "")) == "unanswerable"
            or _is_unanswerable_answer(answer)
        )
        if gold_unanswerable:
            unanswerable_count += 1
            missed_abstentions += int(not predicted_unanswerable)
        else:
            answerable_count += 1
            false_abstentions += int(predicted_unanswerable)

        references = _references(qrel)
        gold_boolean_values = {
            bool(reference["yes_no"])
            for reference in references
            if isinstance(reference.get("yes_no"), bool)
        }
        if gold_boolean_values:
            boolean_count += 1
            if not gold_unanswerable:
                boolean_answerable_count += 1
                normalized_prediction = re.sub(
                    r"[^a-z]+", "", unicodedata.normalize("NFKC", answer).casefold()
                )
                boolean_correct += int(
                    normalized_prediction in {"yes", "no"}
                    and any(
                        (normalized_prediction == "yes") == value
                        for value in gold_boolean_values
                    )
                )

        if details.get("answer_contract_status") not in {None, "not_invoked"}:
            contract_response_count += 1
            is_valid = details.get("answer_contract_status") == "valid"
            contract_valid_count += int(is_valid)
            citation_valid_count += int(
                is_valid
                and details.get("answer_contract_citation_validation_passed") is True
            )
        model_abstention_count += int(
            details.get("answer_contract_model_abstained") is True
        )
        answer_estimate = details.get("answer_token_estimate")
        visible_estimate = details.get("user_visible_token_estimate")
        if not isinstance(answer_estimate, (int, float)):
            answer_estimate = (len(answer) + 3) // 4 if answer else 0
        if not isinstance(visible_estimate, (int, float)):
            visible = str(prediction.get("user_visible_answer", answer) or answer)
            visible_estimate = (len(visible) + 3) // 4 if visible else 0
        answer_token_estimates.append(float(answer_estimate))
        visible_token_estimates.append(float(visible_estimate))

    return {
        "gold_answerable_question_count": answerable_count,
        "gold_unanswerable_question_count": unanswerable_count,
        "false_abstention_count": false_abstentions,
        "false_abstention_rate": (
            false_abstentions / answerable_count if answerable_count else None
        ),
        "missed_abstention_count": missed_abstentions,
        "missed_abstention_rate": (
            missed_abstentions / unanswerable_count if unanswerable_count else None
        ),
        "boolean_question_count": boolean_count,
        "boolean_answerable_question_count": boolean_answerable_count,
        "boolean_answer_accuracy": (
            boolean_correct / boolean_answerable_count
            if boolean_answerable_count
            else None
        ),
        "model_unanswerable_count": model_abstention_count,
        "answer_contract_enabled": contract_enabled,
        "answer_contract_response_count": contract_response_count,
        "answer_contract_valid_count": contract_valid_count,
        "answer_contract_parse_failure_count": (
            contract_response_count - contract_valid_count
        ),
        "answer_contract_valid_rate": (
            contract_valid_count / contract_response_count
            if contract_response_count
            else None
        ),
        "answer_contract_citation_valid_count": citation_valid_count,
        "answer_contract_citation_valid_rate": (
            citation_valid_count / contract_response_count
            if contract_response_count
            else None
        ),
        "mean_answer_token_estimate": _mean(answer_token_estimates),
        "p95_answer_token_estimate": percentile(answer_token_estimates, 95),
        "mean_user_visible_token_estimate": _mean(visible_token_estimates),
        "p95_user_visible_token_estimate": percentile(visible_token_estimates, 95),
        "token_estimate_definition": "ceil(character_count / 4); provider token usage was not available in ChatResult",
    }


def _classify_error_types(
    qrel: dict[str, Any],
    prediction: dict[str, Any],
    trace: dict[str, Any],
    case_metrics: dict[str, Any],
) -> list[str]:
    error_types: list[str] = []
    paragraph_sets = _gold_paragraph_sets(qrel)
    gold_paragraph_ids = set().union(*paragraph_sets) if paragraph_sets else set()
    final_candidates = trace.get("final_candidates", [])
    if not isinstance(final_candidates, list):
        final_candidates = []
    top_candidates = [item for item in final_candidates[:10] if isinstance(item, dict)]
    retrieved_paragraph_ids = _top_candidate_paragraphs(top_candidates, limit=10)

    if paragraph_sets and not retrieved_paragraph_ids.intersection(gold_paragraph_ids):
        error_types.append("retrieval_miss")

    pre_candidates = trace.get("pre_rerank_candidates", [])
    if isinstance(pre_candidates, list):
        pre_rerank_paragraph_ids = {
            str(paragraph_id)
            for item in pre_candidates
            if isinstance(item, dict)
            for paragraph_id in item.get("source_paragraph_ids", [])
            if str(paragraph_id)
        }
    else:
        pre_rerank_paragraph_ids = set()
    if (
        paragraph_sets
        and pre_rerank_paragraph_ids.intersection(gold_paragraph_ids)
        and not retrieved_paragraph_ids.intersection(gold_paragraph_ids)
    ):
        error_types.append("rerank_drop")

    gold_section_indices = {
        int(value)
        for value in qrel.get("gold_evidence_section_indices", [])
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    retrieved_section_indices = {
        int(value)
        for candidate in top_candidates
        for value in candidate.get("source_section_indices", [])
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if (
        paragraph_sets
        and gold_section_indices
        and retrieved_section_indices
        and not retrieved_paragraph_ids.intersection(gold_paragraph_ids)
        and not retrieved_section_indices.intersection(gold_section_indices)
    ):
        error_types.append("wrong_section")

    recall_at_10 = float(case_metrics.get("gold_evidence_recall_at_10", 0.0) or 0.0)
    if paragraph_sets and 0 < recall_at_10 < 1:
        error_types.append("evidence_incomplete")

    rounds = trace.get("retrieval_rounds", [])
    if not isinstance(rounds, list):
        rounds = []
    if paragraph_sets:
        for round_record in rounds:
            if not isinstance(round_record, dict):
                continue
            gate = round_record.get("gate", {})
            context_ids = {
                str(value)
                for value in round_record.get("context_evidence_paragraph_ids", [])
                if str(value)
            }
            if (
                isinstance(gate, dict)
                and gate.get("action") == "stop"
                and not _gold_sufficient(context_ids, paragraph_sets)
            ):
                error_types.append("premature_stop")
                break

    if len(rounds) > 1:
        seen_chunk_ids: set[str] = set()
        no_novel_candidates: list[bool] = []
        for round_record in rounds:
            if not isinstance(round_record, dict):
                continue
            candidate_chunk_ids = {
                str(value)
                for value in round_record.get("candidate_chunk_ids", [])
                if str(value)
            }
            declared_new_count = round_record.get("new_chunk_count")
            if isinstance(declared_new_count, int) and not isinstance(declared_new_count, bool):
                novel_count = declared_new_count
            else:
                novel_count = len(candidate_chunk_ids.difference(seen_chunk_ids))
            no_novel_candidates.append(novel_count == 0)
            seen_chunk_ids.update(candidate_chunk_ids)
        if len(no_novel_candidates) > 1 and all(no_novel_candidates[1:]):
            error_types.append("unnecessary_retrieval")

    generation = prediction.get("answer_generation", {})
    if isinstance(generation, dict):
        metadata = generation.get("metadata", {})
        if isinstance(metadata, dict) and int(metadata.get("unsupported_claim_count", 0) or 0) > 0:
            error_types.append("answer_unsupported")
    if (
        qrel.get("no_answer")
        and isinstance(generation, dict)
        and generation
        and not _is_unanswerable_answer(str(prediction.get("answer", "")))
    ):
        error_types.append("unanswerable_failure")
    return list(dict.fromkeys(error_types))


def _binary_sufficiency_metrics(
    predictions: Sequence[bool],
    labels: Sequence[bool],
) -> dict[str, int | float]:
    if len(predictions) != len(labels):
        raise ValueError("sufficiency predictions and labels must have equal length")
    true_positive = sum(predicted and label for predicted, label in zip(predictions, labels))
    false_positive = sum(
        predicted and not label for predicted, label in zip(predictions, labels)
    )
    false_negative = sum(
        not predicted and label for predicted, label in zip(predictions, labels)
    )
    true_negative = sum(
        not predicted and not label for predicted, label in zip(predictions, labels)
    )
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "Sufficiency Precision": precision if predictions else None,
        "Sufficiency Recall": recall if predictions else None,
        "Sufficiency F1": f1 if predictions else None,
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _qasper_question_category(qrel: dict[str, Any]) -> str:
    breadth = max(
        (
            len(
                {
                    int(value)
                    for value in answer.get("evidence_section_indices", [])
                    if isinstance(value, int) and not isinstance(value, bool)
                }
            )
            for answer in _references(qrel)
            if answer.get("evidence_paragraph_ids") and answer.get("evidence_complete", True)
        ),
        default=0,
    )
    if breadth == 1:
        return "local"
    if breadth == 2:
        return "cross_section"
    if breadth >= 3:
        return "global"
    if qrel.get("no_answer") or all(
        answer.get("answer_type") == "none" for answer in _references(qrel)
    ):
        return "unanswerable"
    return "unclassified"


def _quality_stratification(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def summarize(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
        retrieval_items = [item for item in items if int(item.get("relevant_chunk_count", 0)) > 0]
        return {
            "question_count": len(items),
            "mapped_gold_question_count": len(retrieval_items),
            "Answer F1": _mean([float(item["official_answer_f1"]) for item in items]),
            "Evidence F1": _mean([float(item["official_evidence_f1"]) for item in items]),
            "Recall@10": _mean([float(item["recall_at_10"]) for item in retrieval_items]),
            "MRR": _mean([float(item["MRR"]) for item in retrieval_items]),
            "retrieval_metric_denominator": len(retrieval_items),
        }

    type_groups: dict[str, list[dict[str, Any]]] = {}
    mapped_groups: dict[str, list[dict[str, Any]]] = {"mapped": [], "unmapped": []}
    category_groups: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        mapped_groups["mapped" if case.get("mapped_gold_evidence") else "unmapped"].append(case)
        category_groups.setdefault(str(case.get("question_category", "unclassified")), []).append(case)
        for answer_type in case.get("answer_types", []):
            type_groups.setdefault(str(answer_type), []).append(case)
    return {
        "by_answer_type": {
            name: summarize(items) for name, items in sorted(type_groups.items())
        },
        "by_mapped_gold_evidence": {
            name: summarize(items) for name, items in mapped_groups.items()
        },
        "by_evidence_scope": {
            name: summarize(items) for name, items in sorted(category_groups.items())
        },
        "answer_type_groups_are_multi_label": True,
    }


def _official_qasper_metrics(
    qrels: Sequence[dict[str, Any]],
    predictions: Sequence[dict[str, Any]],
    *,
    text_evidence_only: bool,
) -> dict[str, Any]:
    gold: dict[str, list[dict[str, Any]]] = {}
    for qrel in qrels:
        question_id = str(qrel["question_id"])
        references: list[dict[str, Any]] = []
        for answer in _references(qrel):
            evidence = [str(value) for value in answer.get("evidence_texts", [])]
            if text_evidence_only:
                evidence = [value for value in evidence if "FLOAT SELECTED" not in value]
            references.append(
                {
                    "answer": str(answer.get("answer", "")),
                    "evidence": evidence,
                    "type": str(answer.get("answer_type", "abstractive")),
                }
            )
        if not references:
            raise ValueError(f"qrels question {question_id} has no answer annotations")
        gold[question_id] = references

    predicted: dict[str, dict[str, Any]] = {}
    for record in predictions:
        question_id = str(record["question_id"])
        if question_id in predicted:
            raise ValueError(f"duplicate prediction question_id: {question_id}")
        evidence = record.get("predicted_evidence", [])
        if not isinstance(evidence, list):
            raise TypeError(f"predicted_evidence for {question_id} must be a list")
        predicted[question_id] = {
            "answer": str(record.get("answer", "")),
            "evidence": [str(value) for value in evidence],
        }
    return official_evaluator.evaluate(gold, predicted)


def evaluate_qasper_run(
    run_directory: str | Path,
    *,
    root: str | Path | None = None,
    write_metrics: bool = True,
) -> dict[str, Any]:
    """Evaluate an AITrans QASPER run with retrieval and official QASPER metrics."""

    run_path = Path(run_directory).expanduser().resolve()
    manifest = _read_json(run_path / "manifest.json")
    benchmark_directory = benchmark_root(root)
    qrels_path = Path(str(manifest.get("qrels_path", ""))).expanduser()
    if not qrels_path.is_absolute():
        qrels_path = benchmark_directory / qrels_path
    qrels_path = qrels_path.resolve()
    if not qrels_path.is_file():
        raise FileNotFoundError(f"QASPER qrels were not found: {qrels_path}")
    qrels = _read_jsonl(qrels_path)
    predictions = _read_jsonl(run_path / "predictions.jsonl")
    traces = _read_jsonl(run_path / "retrieval_trace.jsonl")
    qrel_by_id = _by_question_id(qrels, label="qrels")
    prediction_by_id = _by_question_id(predictions, label="prediction")
    trace_by_id = _by_question_id(traces, label="trace")
    unknown_predictions = set(prediction_by_id).difference(qrel_by_id)
    unknown_traces = set(trace_by_id).difference(qrel_by_id)
    if unknown_predictions or unknown_traces:
        raise ValueError("run contains question IDs that are absent from its qrels")

    index_root = Path(str(manifest.get("index", {}).get("index_root", ""))).resolve()
    sparse_path = index_root / "bm25_index.json"
    if not sparse_path.is_file():
        raise FileNotFoundError(f"benchmark BM25 chunk catalogue was not found: {sparse_path}")
    chunk_catalog = BM25SparseRetriever(sparse_path).list_chunks()
    paragraph_to_chunks: dict[str, list[str]] = {}
    for chunk in chunk_catalog:
        metadata = chunk.metadata.get("benchmark", {})
        paragraph_ids = (
            metadata.get("source_paragraph_ids", []) if isinstance(metadata, dict) else []
        )
        if not isinstance(paragraph_ids, list):
            continue
        for paragraph_id in paragraph_ids:
            if isinstance(paragraph_id, str) and paragraph_id:
                paragraph_to_chunks.setdefault(paragraph_id, []).append(chunk.chunk_id)
    paragraph_to_chunks_tuple = {
        key: tuple(dict.fromkeys(values)) for key, values in paragraph_to_chunks.items()
    }
    per_question: list[dict[str, Any]] = []
    ai_recall: dict[int, list[float]] = {k: [] for k in EVALUATION_KS}
    eligible_retrieval_cases = 0
    ai_mrr: list[float] = []
    ai_ndcg: list[float] = []
    pre_mrr: list[float] = []
    pre_ndcg: list[float] = []
    paragraph_metrics: dict[str, list[float]] = {
        name: []
        for k in EVALUATION_KS
        for name in (
            f"Gold Evidence Recall@{k}",
            f"Evidence Precision@{k}",
            f"Evidence F1@{k}",
        )
    }
    evidence_mrr: list[float] = []
    context_coverage: list[float] = []
    eligible_paragraph_cases = 0
    component_latencies: dict[str, list[float]] = {
        "total_rag_ms": [],
        "query_planning_ms": [],
        "embedding_ms": [],
        "dense_search_ms": [],
        "sparse_search_ms": [],
        "structural_search_ms": [],
        "fusion_ms": [],
        "rerank_ms": [],
        "small_to_big_ms": [],
        "raptor_summary_search_ms": [],
        "evidence_extraction_ms": [],
        "evidence_scoring_ms": [],
        "answer_generation_ms": [],
    }
    answerer_counts: dict[str, int] = {}
    verification_fallback_count = 0
    policy_abstention_count = 0
    context_token_counts: list[int] = []
    routing_cases = 0
    routing_counts: dict[str, int] = {}
    second_round_cases = 0
    second_round_observed_cases = 0
    retrieval_round_counts: list[float] = []
    sufficiency_cases = 0
    sufficiency_observed_cases = 0
    sufficient_cases = 0
    gate_observed_cases = 0
    gate_evaluation_cases = 0
    gate_excluded_no_gold_cases = 0
    gate_observed_decisions = 0
    gate_sufficiency_predictions: list[bool] = []
    gate_sufficiency_labels: list[bool] = []
    labeled_stop_decisions = 0
    premature_stop_decisions = 0
    premature_stop_cases = 0
    additional_retrieval_rounds = 0
    unnecessary_retrieval_rounds = 0
    unnecessary_retrieval_cases = 0
    initial_evidence_coverage: list[float] = []
    final_evidence_coverage: list[float] = []
    coverage_gain: list[float] = []
    query_planner_invocations = 0
    answerer_invocations = 0
    evidence_extractor_invocations = 0
    assessed_claims = 0
    unsupported_claims = 0
    initial_assessed_claims = 0
    initial_unsupported_claims = 0
    repair_assessed_claims = 0
    repair_unsupported_claims = 0
    claim_repair_attempts = 0
    claim_repair_successes = 0
    requirement_cases = 0
    requirement_reretrieval_cases = 0
    requirement_round_counts: list[float] = []
    requirement_total = 0
    requirement_covered = 0
    requirement_counts_by_type: dict[str, dict[str, int]] = {}

    for question_id, qrel in qrel_by_id.items():
        prediction = prediction_by_id.get(question_id, {})
        trace = trace_by_id.get(question_id, {})
        final_candidates = trace.get("final_candidates", [])
        if not isinstance(final_candidates, list):
            final_candidates = []
        retrieval_candidate_pool = trace.get(
            "retrieval_candidate_pool",
            final_candidates,
        )
        if not isinstance(retrieval_candidate_pool, list):
            retrieval_candidate_pool = final_candidates
        ranked_chunk_ids = [
            str(candidate.get("chunk_id", ""))
            for candidate in retrieval_candidate_pool
            if isinstance(candidate, dict) and candidate.get("chunk_id")
        ]
        stages = trace.get("stages", {})
        pre_ranked = stages.get("pre_rerank_chunk_ids", []) if isinstance(stages, dict) else []
        if not isinstance(pre_ranked, list):
            pre_ranked = []
        pre_ranked = [str(value) for value in pre_ranked]
        paragraph_sets = _gold_paragraph_sets(qrel)
        chunk_sets = _gold_chunk_sets(qrel, paragraph_to_chunks_tuple)
        retrieval_rounds = trace.get("retrieval_rounds", [])
        if not isinstance(retrieval_rounds, list):
            retrieval_rounds = []
        retrieval_round_counts.append(float(len(retrieval_rounds) or 1))
        round_context_paragraphs = [
            {
                str(value)
                for value in round_record.get("context_evidence_paragraph_ids", [])
                if str(value)
            }
            if isinstance(round_record, dict)
            else set()
            for round_record in retrieval_rounds
        ]
        cumulative_round_contexts: list[set[str]] = []
        cumulative_context: set[str] = set()
        for round_index, round_context in enumerate(round_context_paragraphs):
            round_record = retrieval_rounds[round_index]
            if (
                isinstance(round_record, dict)
                and round_record.get("context_is_cumulative") is True
            ):
                cumulative_context = set(round_context)
            else:
                cumulative_context.update(round_context)
            cumulative_round_contexts.append(set(cumulative_context))
        final_round_context = (
            cumulative_round_contexts[-1]
            if cumulative_round_contexts
            else {
                str(value)
                for value in trace.get("context_evidence_paragraph_ids", [])
                if str(value)
            }
        )
        initial_round_context = (
            round_context_paragraphs[0]
            if round_context_paragraphs
            else final_round_context
        )

        initial_coverage = _best_paragraph_coverage(
            initial_round_context,
            paragraph_sets,
        )
        final_coverage = _best_paragraph_coverage(final_round_context, paragraph_sets)
        if paragraph_sets:
            initial_evidence_coverage.append(initial_coverage)
            final_evidence_coverage.append(final_coverage)
            coverage_gain.append(final_coverage - initial_coverage)
        relevant_union = set().union(*chunk_sets) if chunk_sets else set()
        case_metrics: dict[str, Any] = {
            "question_id": question_id,
            "relevant_chunk_count": len(relevant_union),
            "gold_paragraph_count_by_annotator": [len(item) for item in paragraph_sets],
            "answer_types": sorted(
                {
                    str(answer.get("answer_type", "abstractive"))
                    for answer in _references(qrel)
                }
            ),
            "mapped_gold_evidence": bool(relevant_union),
            "question_category": _qasper_question_category(qrel),
            "retrieval_candidate_count": len(retrieval_candidate_pool),
            "selected_evidence_count": len(final_candidates),
        }
        requirement_records = trace.get("evidence_requirements", [])
        if (
            trace.get("adaptive_variant") == "requirement_aware"
            and isinstance(requirement_records, list)
        ):
            valid_requirements = [
                item for item in requirement_records if isinstance(item, dict)
            ]
            requirement_cases += 1
            requirement_reretrieval_cases += int(
                bool(trace.get("second_round"))
            )
            requirement_round_counts.append(float(len(retrieval_rounds) or 1))
            requirement_total += len(valid_requirements)
            requirement_covered += sum(
                item.get("status") == "covered" for item in valid_requirements
            )
            for requirement in valid_requirements:
                requirement_type = str(requirement.get("type", "unknown"))
                totals = requirement_counts_by_type.setdefault(
                    requirement_type,
                    {"total": 0, "covered": 0},
                )
                totals["total"] += 1
                totals["covered"] += int(requirement.get("status") == "covered")
            case_metrics["evidence_requirements"] = valid_requirements
            case_metrics["requirement_coverage"] = (
                sum(item.get("status") == "covered" for item in valid_requirements)
                / len(valid_requirements)
                if valid_requirements
                else 0.0
            )
        raptor_category = str(trace.get("raptor_category", "") or "")
        if raptor_category:
            case_metrics["raptor_category"] = raptor_category
        context_token_count = sum(
            int(
                candidate.get("context_window", {}).get("token_count", 0)
                if isinstance(candidate.get("context_window"), dict)
                else candidate.get("token_count", 0)
                or 0
            )
            for candidate in final_candidates
            if isinstance(candidate, dict)
        )
        context_token_counts.append(context_token_count)
        case_metrics["context_token_count"] = context_token_count
        for k in EVALUATION_KS:
            chunk_recall = max(
                (recall_at_k(ranked_chunk_ids, items, k) for items in chunk_sets),
                default=0.0,
            )
            candidate_predicted_paragraphs = _top_candidate_paragraphs(
                [
                    item
                    for item in retrieval_candidate_pool
                    if isinstance(item, dict)
                ],
                limit=k,
            )
            _candidate_precision, candidate_paragraph_recall, _candidate_f1 = (
                _paragraph_precision_recall_f1(
                    candidate_predicted_paragraphs,
                    paragraph_sets,
                )
            )
            if chunk_sets:
                ai_recall[k].append(chunk_recall)
            predicted_paragraphs = _top_candidate_paragraphs(
                [item for item in final_candidates if isinstance(item, dict)],
                limit=k,
            )
            precision, paragraph_recall, f1 = _paragraph_precision_recall_f1(
                predicted_paragraphs,
                paragraph_sets,
            )
            if paragraph_sets:
                paragraph_metrics[f"Gold Evidence Recall@{k}"].append(paragraph_recall)
                paragraph_metrics[f"Evidence Precision@{k}"].append(precision)
                paragraph_metrics[f"Evidence F1@{k}"].append(f1)
            case_metrics[f"recall_at_{k}"] = chunk_recall
            case_metrics[f"candidate_gold_evidence_recall_at_{k}"] = (
                candidate_paragraph_recall
            )
            case_metrics[f"gold_evidence_recall_at_{k}"] = paragraph_recall
            case_metrics[f"evidence_precision_at_{k}"] = precision
            case_metrics[f"evidence_f1_at_{k}"] = f1

        ai_mrr_value = max(
            (reciprocal_rank(ranked_chunk_ids, items) for items in chunk_sets),
            default=0.0,
        )
        ai_ndcg_value = max(
            (ndcg_at_k(ranked_chunk_ids, {item: 1 for item in items}, 10) for items in chunk_sets),
            default=0.0,
        )
        pre_mrr_value = max(
            (reciprocal_rank(pre_ranked, items) for items in chunk_sets),
            default=0.0,
        )
        pre_ndcg_value = max(
            (ndcg_at_k(pre_ranked, {item: 1 for item in items}, 10) for items in chunk_sets),
            default=0.0,
        )
        if chunk_sets:
            eligible_retrieval_cases += 1
            ai_mrr.append(ai_mrr_value)
            ai_ndcg.append(ai_ndcg_value)
            pre_mrr.append(pre_mrr_value)
            pre_ndcg.append(pre_ndcg_value)
        case_metrics["MRR"] = ai_mrr_value
        case_metrics["nDCG@10"] = ai_ndcg_value
        first_relevant_rank = next(
            (
                rank
                for rank, candidate in enumerate(final_candidates, 1)
                if isinstance(candidate, dict)
                and set(candidate.get("source_paragraph_ids", [])).intersection(
                    set().union(*paragraph_sets) if paragraph_sets else set()
                )
            ),
            None,
        )
        evidence_mrr_value = 1 / first_relevant_rank if first_relevant_rank else 0.0
        if paragraph_sets:
            evidence_mrr.append(evidence_mrr_value)
        retrieved_context_pids = {
            str(value)
            for value in trace.get("context_evidence_paragraph_ids", [])
            if str(value)
        }
        if not retrieved_context_pids:
            retrieved_context_pids = set().union(
                *(
                    set(candidate.get("source_paragraph_ids", []))
                    for candidate in final_candidates
                    if isinstance(candidate, dict)
                )
            ) if final_candidates else set()
        _context_precision, context_recall, _context_f1 = _paragraph_precision_recall_f1(
            retrieved_context_pids,
            paragraph_sets,
        )
        if paragraph_sets:
            context_coverage.append(context_recall)
            eligible_paragraph_cases += 1
        case_metrics["gold_evidence_mrr"] = evidence_mrr_value
        case_metrics["context_evidence_coverage"] = context_recall
        case_prediction = prediction_by_id.get(
            question_id,
            {"question_id": question_id, "answer": "", "predicted_evidence": []},
        )
        official_case = _official_qasper_metrics(
            [qrel],
            [case_prediction],
            text_evidence_only=False,
        )
        case_metrics["official_answer_f1"] = official_case["Answer F1"]
        case_metrics["official_evidence_f1"] = official_case["Evidence F1"]
        case_metrics["official_answer_f1_by_type"] = official_case[
            "Answer F1 by type"
        ]
        per_question.append(case_metrics)

        latency = float(trace.get("latency_ms", 0.0) or 0.0)
        component_latencies["total_rag_ms"].append(latency)
        retrieval_metadata = trace.get("retrieval_metadata", {})
        if isinstance(retrieval_metadata, dict):
            for key in (
                "embedding_ms",
                "query_planning_ms",
                "dense_search_ms",
                "sparse_search_ms",
                "structural_search_ms",
                "fusion_ms",
                "rerank_ms",
                "small_to_big_ms",
                "raptor_summary_search_ms",
                "evidence_extraction_ms",
                "evidence_scoring_ms",
            ):
                component_latencies[key].append(float(retrieval_metadata.get(key, 0.0) or 0.0))
            evidence_extractor_invocations += int(
                retrieval_metadata.get("evidence_extractor_invocations", 0) or 0
            )
        planner_invocation_count = (
            retrieval_metadata.get("query_planner_invocation_count")
            if isinstance(retrieval_metadata, dict)
            else None
        )
        query_planner_invocations += (
            int(planner_invocation_count)
            if isinstance(planner_invocation_count, int)
            and not isinstance(planner_invocation_count, bool)
            and planner_invocation_count >= 0
            else int(bool(trace.get("query_planner_invoked")))
        )
        answer_metadata = prediction.get("answer_generation", {})
        if isinstance(answer_metadata, dict) and answer_metadata:
            answer_details = answer_metadata.get("metadata", {})
            if not isinstance(answer_details, dict):
                answer_details = {}
            reported_answer_calls = answer_details.get("answer_llm_invocation_count")
            if (
                isinstance(reported_answer_calls, int)
                and not isinstance(reported_answer_calls, bool)
            ):
                answerer_invocations += max(0, reported_answer_calls)
            else:
                answerer_invocations += int(
                    not bool(answer_details.get("abstained"))
                ) + max(
                    0,
                    int(answer_details.get("extra_llm_invocation_count", 0) or 0),
                )
            claim_count = answer_details.get("claim_count")
            unsupported_claim_count = answer_details.get("unsupported_claim_count")
            if (
                isinstance(claim_count, int)
                and not isinstance(claim_count, bool)
                and claim_count > 0
                and isinstance(unsupported_claim_count, int)
                and not isinstance(unsupported_claim_count, bool)
            ):
                assessed_claims += claim_count
                unsupported_claims += max(
                    0,
                    min(claim_count, unsupported_claim_count),
                )
            initial_claim_count = answer_details.get("initial_claim_count")
            initial_unsupported_claim_count = answer_details.get(
                "initial_unsupported_claim_count"
            )
            if (
                isinstance(initial_claim_count, int)
                and not isinstance(initial_claim_count, bool)
                and initial_claim_count > 0
                and isinstance(initial_unsupported_claim_count, int)
                and not isinstance(initial_unsupported_claim_count, bool)
            ):
                initial_assessed_claims += initial_claim_count
                initial_unsupported_claims += max(
                    0,
                    min(initial_claim_count, initial_unsupported_claim_count),
                )
            repair_claim_count = answer_details.get("repair_claim_count")
            repair_unsupported_claim_count = answer_details.get(
                "repair_unsupported_claim_count"
            )
            if (
                isinstance(repair_claim_count, int)
                and not isinstance(repair_claim_count, bool)
                and repair_claim_count > 0
                and isinstance(repair_unsupported_claim_count, int)
                and not isinstance(repair_unsupported_claim_count, bool)
            ):
                repair_assessed_claims += repair_claim_count
                repair_unsupported_claims += max(
                    0,
                    min(repair_claim_count, repair_unsupported_claim_count),
                )
            claim_repair_attempts += int(
                answer_details.get("claim_repair_attempted") is True
            )
            claim_repair_successes += int(
                answer_details.get("claim_repair_succeeded") is True
            )
            component_latencies["answer_generation_ms"].append(
                float(answer_metadata.get("latency_ms", 0.0) or 0.0)
            )
            provider = str(answer_metadata.get("provider", "") or "")
            if answer_details.get("fallback_applied") is True:
                verification_fallback_count += 1
                configured_model = manifest.get("answer_model", {})
                actual_provider = (
                    str(configured_model.get("provider", "")).strip()
                    if isinstance(configured_model, dict)
                    else ""
                )
                if actual_provider:
                    answerer_counts[actual_provider] = (
                        answerer_counts.get(actual_provider, 0) + 1
                    )
            elif answer_details.get("abstained") is True:
                policy_abstention_count += 1
            elif provider and provider.casefold() != "policy":
                answerer_counts[provider] = answerer_counts.get(provider, 0) + 1
        routing = trace.get("routing")
        if isinstance(routing, dict):
            routing_cases += 1
            route_name = str(
                routing.get("route", routing.get("strategy", routing.get("decision", "")))
            ).strip()
            if route_name:
                routing_counts[route_name] = routing_counts.get(route_name, 0) + 1
        if "second_round" in trace:
            second_round_observed_cases += 1
            second_round_cases += int(bool(trace.get("second_round")))
        sufficiency = trace.get("sufficiency")
        gate_round_metrics: list[dict[str, Any]] = []
        query_gate_observed = False
        query_gate_evaluable = bool(paragraph_sets)
        query_premature_stop = False
        query_unnecessary_retrieval = False
        observed_gate_rounds = [
            (index, round_record, round_record.get("gate"))
            for index, round_record in enumerate(retrieval_rounds)
            if isinstance(round_record, dict)
            and isinstance(round_record.get("gate"), dict)
        ]
        if not observed_gate_rounds and isinstance(sufficiency, dict):
            observed_gate_rounds = [(-1, {}, sufficiency)]
        for round_index, round_record, gate in observed_gate_rounds:
            query_gate_observed = True
            gate_observed_decisions += 1
            if round_index >= 0 and round_index < len(cumulative_round_contexts):
                round_context = cumulative_round_contexts[round_index]
            else:
                round_context = final_round_context
            gold_sufficient = _gold_sufficient(round_context, paragraph_sets)
            action = str(gate.get("action", ""))
            reasons = gate.get("reason_codes", [])
            predicted_sufficient = gate.get("sufficient")
            if not isinstance(predicted_sufficient, bool):
                predicted_sufficient = (
                    action == "stop"
                    and isinstance(reasons, list)
                    and "evidence_sufficient" in reasons
                )
            if query_gate_evaluable:
                gate_sufficiency_predictions.append(predicted_sufficient)
                gate_sufficiency_labels.append(gold_sufficient)
                if action == "stop":
                    labeled_stop_decisions += 1
                    if not gold_sufficient:
                        premature_stop_decisions += 1
                        query_premature_stop = True
            if round_index > 0:
                additional_retrieval_rounds += int(query_gate_evaluable)
                previous_context = cumulative_round_contexts[round_index - 1]
                if query_gate_evaluable and _gold_sufficient(previous_context, paragraph_sets):
                    unnecessary_retrieval_rounds += 1
                    query_unnecessary_retrieval = True
            gate_round_metrics.append(
                {
                    "round": round_record.get("round", round_index + 1),
                    "action": action,
                    "predicted_sufficient": predicted_sufficient,
                    "gold_sufficient": gold_sufficient if query_gate_evaluable else None,
                    "cumulative_context_paragraph_ids": sorted(round_context),
                    "reason_codes": reasons if isinstance(reasons, list) else [],
                }
            )
        if query_gate_observed:
            gate_observed_cases += 1
            if query_gate_evaluable:
                gate_evaluation_cases += 1
            else:
                gate_excluded_no_gold_cases += 1
            premature_stop_cases += int(query_premature_stop)
            unnecessary_retrieval_cases += int(query_unnecessary_retrieval)
        case_metrics["evidence_gate_rounds"] = gate_round_metrics
        if isinstance(sufficiency, dict):
            sufficiency_cases += 1
            sufficient = sufficiency.get("sufficient", sufficiency.get("is_sufficient"))
            if isinstance(sufficient, bool):
                sufficiency_observed_cases += 1
                sufficient_cases += int(sufficient)

    prediction_records = list(prediction_by_id.values())
    official_full = _official_qasper_metrics(
        qrels,
        prediction_records,
        text_evidence_only=False,
    )
    official_text_only = _official_qasper_metrics(
        qrels,
        prediction_records,
        text_evidence_only=True,
    )
    mapped_gold_cases = [
        case for case in per_question if case.get("mapped_gold_evidence")
    ]
    candidate_pool_evidence = {
        "evaluated_cases": len(mapped_gold_cases),
        **{
            f"Gold Evidence Recall@{k}": _mean(
                [
                    float(case[f"candidate_gold_evidence_recall_at_{k}"])
                    for case in mapped_gold_cases
                ]
            )
            for k in EVALUATION_KS
        },
        "definition": "best annotator paragraph recall from the complete retrieval candidate pool, before evidence selection",
    }
    retrieval_count = len(qrel_by_id)
    metrics: dict[str, Any] = {
        "metric_version": 4,
        "run_id": manifest.get("run_id", run_path.name),
        "dataset": manifest.get("dataset", "qasper"),
        "split": manifest.get("split", ""),
        "question_count": retrieval_count,
        "prediction_count": len(prediction_by_id),
        "trace_count": len(trace_by_id),
        "missing_predictions": len(set(qrel_by_id).difference(prediction_by_id)),
        "missing_traces": len(set(qrel_by_id).difference(trace_by_id)),
        "ai_trans_retrieval": {
            "evaluated_cases": eligible_retrieval_cases,
            "Recall@5": _mean(ai_recall[5]),
            "Recall@10": _mean(ai_recall[10]),
            "Recall@20": _mean(ai_recall[20]),
            "MRR": _mean(ai_mrr),
            "nDCG@10": _mean(ai_ndcg),
            "pre_rerank_MRR": _mean(pre_mrr),
            "post_rerank_MRR": _mean(ai_mrr),
            "MRR_delta": _mean(ai_mrr) - _mean(pre_mrr),
            "pre_rerank_nDCG@10": _mean(pre_ndcg),
            "post_rerank_nDCG@10": _mean(ai_ndcg),
            "nDCG@10_delta": _mean(ai_ndcg) - _mean(pre_ndcg),
        },
        "candidate_pool_evidence": candidate_pool_evidence,
        "paragraph_evidence": {
            "evaluated_cases": eligible_paragraph_cases,
            **{
                metric_name: _mean(values)
                for metric_name, values in paragraph_metrics.items()
            },
            "Gold Evidence MRR": _mean(evidence_mrr),
            "Context Evidence Coverage": _mean(context_coverage),
            "definition": {
                "gold_evidence_recall": "best annotator paragraph recall at rank K",
                "evidence_precision": "best annotator paragraph precision at rank K",
                "evidence_f1": "best annotator paragraph F1 at rank K",
                "gold_evidence_mrr": "first final chunk intersecting any annotator gold paragraph set",
                "context_evidence_coverage": "best annotator paragraph recall over the final grounded context",
            },
        },
        "official_qasper": {
            "all_evidence": official_full,
            "text_evidence_only": official_text_only,
        },
        "performance_ms": {
            key: {
                "p50": round(percentile(values, 50), 3),
                "p95": round(percentile(values, 95), 3),
                "samples": len(values),
            }
            for key, values in component_latencies.items()
        },
        "context_metrics": {
            "evaluated_cases": len(context_token_counts),
            "Context Tokens": _mean(context_token_counts),
            "total_context_tokens": sum(context_token_counts),
            "p50_context_tokens": percentile(context_token_counts, 50),
            "p95_context_tokens": percentile(context_token_counts, 95),
        },
        "adaptive_retrieval": {
            "evaluated_cases": len(initial_evidence_coverage),
            "Mean Retrieval Rounds": _mean(retrieval_round_counts),
            "Initial Evidence Coverage": _mean(initial_evidence_coverage),
            "Final Evidence Coverage": _mean(final_evidence_coverage),
            "Coverage Gain": _mean(coverage_gain),
            "second_round_rate": (
                second_round_cases / second_round_observed_cases
                if second_round_observed_cases
                else None
            ),
            "Premature Stop Rate": (
                premature_stop_decisions / labeled_stop_decisions
                if labeled_stop_decisions
                else None
            ),
            "Unnecessary Retrieval Rate": (
                unnecessary_retrieval_rounds / additional_retrieval_rounds
                if additional_retrieval_rounds
                else None
            ),
            "Premature Stop Case Rate": (
                premature_stop_cases / gate_evaluation_cases
                if gate_evaluation_cases
                else None
            ),
            "Unnecessary Retrieval Case Rate": (
                unnecessary_retrieval_cases / gate_evaluation_cases
                if gate_evaluation_cases
                else None
            ),
            "gate_observed_cases": gate_observed_cases,
            "gate_evaluation_cases": gate_evaluation_cases,
            "gate_observed_decisions": gate_observed_decisions,
            "premature_stop_decisions": premature_stop_decisions,
            "labeled_stop_decisions": labeled_stop_decisions,
            "additional_retrieval_rounds": additional_retrieval_rounds,
            "unnecessary_retrieval_rounds": unnecessary_retrieval_rounds,
            "query_planner_invocations": query_planner_invocations,
            "answerer_invocations": answerer_invocations,
            "evidence_extractor_invocations": evidence_extractor_invocations,
            "estimated_llm_invocations": (
                query_planner_invocations
                + answerer_invocations
                + evidence_extractor_invocations
            ),
        },
        "evidence_gate_evaluation": {
            "evaluated_decisions": len(gate_sufficiency_labels),
            "evaluated_question_count": gate_evaluation_cases,
            "excluded_no_gold_evidence_cases": gate_excluded_no_gold_cases,
            "definition": {
                "gold_sufficient": "cumulative context includes every paragraph in at least one annotator's complete non-empty evidence set",
                "sufficiency_metrics": "one binary prediction/label pair per observed gate decision",
                "empty_gold": "questions without mapped gold evidence are excluded from sufficiency classification",
            },
            **_binary_sufficiency_metrics(
                gate_sufficiency_predictions,
                gate_sufficiency_labels,
            ),
        },
        "evidence_requirement_evaluation": {
            "evaluated_questions": requirement_cases,
            "requirement_count": requirement_total,
            "covered_requirement_count": requirement_covered,
            "missing_requirement_count": requirement_total - requirement_covered,
            "Requirement Coverage": (
                requirement_covered / requirement_total if requirement_total else None
            ),
            "Re-retrieval Case Rate": (
                requirement_reretrieval_cases / requirement_cases
                if requirement_cases
                else None
            ),
            "Mean Retrieval Rounds": _mean(requirement_round_counts)
            if requirement_round_counts
            else None,
            "by_type": {
                name: {
                    **counts,
                    "coverage": (
                        counts["covered"] / counts["total"]
                        if counts["total"]
                        else None
                    ),
                }
                for name, counts in sorted(requirement_counts_by_type.items())
            },
            "definition": "requirement coverage is a runtime lexical evidence heuristic, separate from QASPER gold evidence recall",
        },
        "adaptive_metrics": {
            "routing_cases": routing_cases,
            "routing_counts": dict(sorted(routing_counts.items())),
            "second_round_cases": second_round_cases,
            "second_round_observed_cases": second_round_observed_cases,
            "second_round_rate": (
                second_round_cases / second_round_observed_cases
                if second_round_observed_cases
                else None
            ),
            "sufficiency_cases": sufficiency_cases,
            "sufficiency_rate": (
                sufficient_cases / sufficiency_observed_cases
                if sufficiency_observed_cases
                else None
            ),
            "status": (
                "available"
                if routing_cases
                or second_round_observed_cases
                or sufficiency_cases
                or any(
                    isinstance(trace.get("retrieval_rounds"), list)
                    and trace.get("retrieval_rounds")
                    for trace in trace_by_id.values()
                )
                else "not_recorded_by_this_run"
            ),
        },
        "answer_provider_counts": dict(sorted(answerer_counts.items())),
        "verification_fallback_count": verification_fallback_count,
        "policy_abstention_count": policy_abstention_count,
        "groundedness_metrics": {
            "assessed_claims": assessed_claims,
            "unsupported_claims": unsupported_claims,
            "Unsupported Claim Rate": (
                unsupported_claims / assessed_claims if assessed_claims else None
            ),
            "initial_assessed_claims": initial_assessed_claims,
            "initial_unsupported_claims": initial_unsupported_claims,
            "Initial Unsupported Claim Rate": (
                initial_unsupported_claims / initial_assessed_claims
                if initial_assessed_claims
                else None
            ),
            "repair_assessed_claims": repair_assessed_claims,
            "repair_unsupported_claims": repair_unsupported_claims,
            "Repair Unsupported Claim Rate": (
                repair_unsupported_claims / repair_assessed_claims
                if repair_assessed_claims
                else None
            ),
            "claim_repair_attempts": claim_repair_attempts,
            "claim_repair_successes": claim_repair_successes,
        },
        "evidence_selection": {
            "extractor_invocations": evidence_extractor_invocations,
        },
        "per_question": per_question,
        "quality_stratification": _quality_stratification(per_question),
    }
    error_counts = {
        "retrieval_miss": 0,
        "rerank_drop": 0,
        "wrong_section": 0,
        "evidence_incomplete": 0,
        "premature_stop": 0,
        "unnecessary_retrieval": 0,
        "answer_unsupported": 0,
        "unanswerable_failure": 0,
        "latency_outlier": 0,
    }
    latency_p95 = float(metrics["performance_ms"]["total_rag_ms"]["p95"])
    for case_metrics in per_question:
        question_id = str(case_metrics["question_id"])
        error_types = _classify_error_types(
            qrel_by_id[question_id],
            prediction_by_id.get(question_id, {}),
            trace_by_id.get(question_id, {}),
            case_metrics,
        )
        trace_latency = float(trace_by_id.get(question_id, {}).get("latency_ms", 0.0) or 0.0)
        if component_latencies["total_rag_ms"] and trace_latency > latency_p95:
            error_types.append("latency_outlier")
        case_metrics["error_types"] = list(dict.fromkeys(error_types))
        for error_type in case_metrics["error_types"]:
            error_counts[error_type] += 1
    metrics["error_taxonomy"] = {
        "question_count": retrieval_count,
        "counts": error_counts,
        "multi_label": True,
    }
    metrics["answer_behavior"] = _answer_behavior_metrics(
        qrel_by_id,
        prediction_by_id,
        contract_enabled=bool(manifest.get("answer_contract")),
    )
    tagged_raptor_questions = {
        str(item["question_id"]): str(item["raptor_category"])
        for item in per_question
        if item.get("raptor_category")
    }
    if tagged_raptor_questions:
        qrel_by_id_for_categories = qrel_by_id
        prediction_by_id_for_categories = prediction_by_id
        category_ids = {
            "Local": [
                question_id
                for question_id, category in tagged_raptor_questions.items()
                if category == "local"
            ],
            "Cross-section": [
                question_id
                for question_id, category in tagged_raptor_questions.items()
                if category == "cross_section"
            ],
            "Global": [
                question_id
                for question_id, category in tagged_raptor_questions.items()
                if category == "global"
            ],
            "Overall": list(tagged_raptor_questions),
        }
        case_by_id = {str(item["question_id"]): item for item in per_question}
        category_metrics: dict[str, Any] = {}
        for category_name, question_ids in category_ids.items():
            cases = [case_by_id[question_id] for question_id in question_ids]
            eligible_cases = [case for case in cases if case["relevant_chunk_count"] > 0]
            category_qrels = [qrel_by_id_for_categories[item] for item in question_ids]
            category_predictions = [
                prediction_by_id_for_categories.get(item, {"question_id": item})
                for item in question_ids
            ]
            official = _official_qasper_metrics(
                category_qrels,
                category_predictions,
                text_evidence_only=False,
            ) if question_ids else {}
            category_metrics[category_name] = {
                "question_count": len(question_ids),
                "evidence_evaluated_cases": len(eligible_cases),
                "Recall@10": _mean(
                    [float(case["recall_at_10"]) for case in eligible_cases]
                ) if eligible_cases else None,
                "Gold Evidence Recall@10": _mean(
                    [float(case["gold_evidence_recall_at_10"]) for case in eligible_cases]
                ) if eligible_cases else None,
                "Evidence F1@20": _mean(
                    [float(case["evidence_f1_at_20"]) for case in eligible_cases]
                ) if eligible_cases else None,
                "MRR": _mean([float(case["MRR"]) for case in eligible_cases])
                if eligible_cases
                else None,
                "nDCG@10": _mean(
                    [float(case["nDCG@10"]) for case in eligible_cases]
                ) if eligible_cases else None,
                "Context Evidence Coverage": _mean(
                    [float(case["context_evidence_coverage"]) for case in eligible_cases]
                ) if eligible_cases else None,
                "official_qasper": official,
            }
        category_metrics["unanswerable_question_count"] = sum(
            category == "unanswerable" for category in tagged_raptor_questions.values()
        )
        category_metrics["unclassified_question_count"] = sum(
            category == "unclassified" for category in tagged_raptor_questions.values()
        )
        metrics["raptor_category_metrics"] = category_metrics
    if write_metrics:
        atomic_write_json(run_path / "metrics.json", metrics)
    return metrics


__all__ = ["EVALUATION_KS", "evaluate_qasper_run"]
