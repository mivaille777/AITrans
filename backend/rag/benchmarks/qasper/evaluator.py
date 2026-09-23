from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from backend.rag.benchmarks.common import atomic_write_json, benchmark_root
from backend.rag.evaluation import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from backend.rag.sparse.store import BM25SparseRetriever
from third_party.qasper import official_evaluator

EVALUATION_KS = (5, 10, 20)


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
        "answer_generation_ms": [],
    }
    answerer_counts: dict[str, int] = {}
    context_token_counts: list[int] = []
    routing_cases = 0
    routing_counts: dict[str, int] = {}
    second_round_cases = 0
    second_round_observed_cases = 0
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

    for question_id, qrel in qrel_by_id.items():
        prediction = prediction_by_id.get(question_id, {})
        trace = trace_by_id.get(question_id, {})
        final_candidates = trace.get("final_candidates", [])
        if not isinstance(final_candidates, list):
            final_candidates = []
        ranked_chunk_ids = [
            str(candidate.get("chunk_id", ""))
            for candidate in final_candidates
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
        round_context_paragraphs = [
            {
                str(value)
                for value in round_record.get("context_evidence_paragraph_ids", [])
                if str(value)
            }
            for round_record in retrieval_rounds
            if isinstance(round_record, dict)
        ]
        cumulative_round_contexts: list[set[str]] = []
        cumulative_context: set[str] = set()
        for round_context in round_context_paragraphs:
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
        }
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
                "rerank_ms",
                "small_to_big_ms",
            ):
                component_latencies[key].append(float(retrieval_metadata.get(key, 0.0) or 0.0))
        query_planner_invocations += int(bool(trace.get("query_planner_invoked")))
        answer_metadata = prediction.get("answer_generation", {})
        if isinstance(answer_metadata, dict) and answer_metadata:
            answer_details = answer_metadata.get("metadata", {})
            if not isinstance(answer_details, dict):
                answer_details = {}
            answerer_invocations += int(
                not bool(answer_details.get("abstained"))
            )
            component_latencies["answer_generation_ms"].append(
                float(answer_metadata.get("latency_ms", 0.0) or 0.0)
            )
            provider = str(answer_metadata.get("provider", "") or "")
            if provider:
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
    retrieval_count = len(qrel_by_id)
    metrics: dict[str, Any] = {
        "metric_version": 3,
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
            "estimated_llm_invocations": query_planner_invocations + answerer_invocations,
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
        "per_question": per_question,
    }
    if write_metrics:
        atomic_write_json(run_path / "metrics.json", metrics)
    return metrics


__all__ = ["EVALUATION_KS", "evaluate_qasper_run"]
