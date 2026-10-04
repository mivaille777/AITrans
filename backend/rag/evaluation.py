from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import log2
from statistics import mean
from typing import Any

from pydantic import Field

from backend.rag.evaluation_dataset import (
    RagEvaluationCase,
    RagEvaluationPrediction,
)
from backend.rag.evaluation_protocol import ClaimAssessment, assessment_map
from backend.rag.models import RagContractModel


def recall_at_k(
    ranked_chunk_ids: Sequence[str], relevant_chunk_ids: Iterable[str], k: int
) -> float:
    if k < 1:
        raise ValueError("k must be greater than zero")
    relevant = set(relevant_chunk_ids)
    if not relevant:
        return 0.0
    return len(relevant.intersection(ranked_chunk_ids[:k])) / len(relevant)


def reciprocal_rank(
    ranked_chunk_ids: Sequence[str], relevant_chunk_ids: Iterable[str]
) -> float:
    relevant = set(relevant_chunk_ids)
    for rank, chunk_id in enumerate(ranked_chunk_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_chunk_ids: Sequence[str], relevance_grades: dict[str, int], k: int
) -> float:
    if k < 1:
        raise ValueError("k must be greater than zero")

    def discounted_gain(grades: Sequence[int]) -> float:
        return sum(
            ((2**grade) - 1) / log2(rank + 1)
            for rank, grade in enumerate(grades, start=1)
        )

    observed = [relevance_grades.get(chunk_id, 0) for chunk_id in ranked_chunk_ids[:k]]
    ideal = sorted(relevance_grades.values(), reverse=True)[:k]
    ideal_gain = discounted_gain(ideal)
    return discounted_gain(observed) / ideal_gain if ideal_gain else 0.0


def percentile(values: Sequence[float], percentage: float) -> float:
    if not 0 <= percentage <= 100:
        raise ValueError("percentage must be between 0 and 100")
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentage / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class RagCaseEvaluation(RagContractModel):
    case_id: str
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_20: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    pre_rerank_reciprocal_rank: float = Field(ge=0.0, le=1.0)
    pre_rerank_ndcg_at_10: float = Field(ge=0.0, le=1.0)
    post_rerank_reciprocal_rank: float = Field(default=0.0, ge=0.0, le=1.0)
    post_rerank_ndcg_at_10: float = Field(default=0.0, ge=0.0, le=1.0)
    no_answer_correct: bool | None = None


class RagRetrievalMetrics(RagContractModel):
    evaluated_cases: int = Field(ge=0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_20: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    no_answer_accuracy: float = Field(ge=0.0, le=1.0)
    no_answer_cases: int = Field(ge=0)
    # Routing and evidence metrics are kept beside retrieval metrics because
    # the Evaluation tab renders this object directly.  They default to zero
    # so a report always has a stable, measurable shape, including for an
    # empty or legacy dataset.
    routing_cases: int = Field(default=0, ge=0)
    retrieval_trigger_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_trigger_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    unnecessary_retrieval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_retrieval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    scope_violation_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    second_round_retrieval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_sufficiency_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class RagRerankerComparison(RagContractModel):
    mrr_before: float = Field(ge=0.0, le=1.0)
    mrr_after: float = Field(ge=0.0, le=1.0)
    mrr_delta: float
    ndcg_at_10_before: float = Field(ge=0.0, le=1.0)
    ndcg_at_10_after: float = Field(ge=0.0, le=1.0)
    ndcg_at_10_delta: float


class RagCitationMetrics(RagContractModel):
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_recall: float = Field(ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    annotated_claims: int = Field(ge=0)
    assessed_claims: int = Field(ge=0)


class RagLatencyPercentiles(RagContractModel):
    p50: float = Field(ge=0.0)
    p95: float = Field(ge=0.0)
    samples: int = Field(ge=0)


class RagPerformanceMetrics(RagContractModel):
    query_embedding_ms: RagLatencyPercentiles
    dense_search_ms: RagLatencyPercentiles
    bm25_ms: RagLatencyPercentiles
    rerank_ms: RagLatencyPercentiles
    total_rag_ms: RagLatencyPercentiles


class RagEvaluationReport(RagContractModel):
    total_cases: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    retrieval: RagRetrievalMetrics
    reranker: RagRerankerComparison
    citations: RagCitationMetrics
    performance: RagPerformanceMetrics
    cases: list[RagCaseEvaluation] = Field(default_factory=list)
    production: dict[str, Any] = Field(default_factory=dict)


def _average(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def _latency(values: Sequence[float]) -> RagLatencyPercentiles:
    return RagLatencyPercentiles(
        p50=round(percentile(values, 50), 3),
        p95=round(percentile(values, 95), 3),
        samples=len(values),
    )


def _citation_metrics(
    cases: Sequence[RagEvaluationCase],
    predictions: dict[str, RagEvaluationPrediction],
    assessments: Sequence[ClaimAssessment] = (),
) -> RagCitationMetrics:
    independent = assessment_map(assessments)
    annotated_links: set[tuple[str, str, str]] = set()
    annotated_claims: set[tuple[str, str]] = set()
    predicted_links: set[tuple[str, str, str]] = set()
    covered_claims: set[tuple[str, str]] = set()
    assessed_claims = 0
    unsupported_claims = 0

    for case in cases:
        annotations = {claim.claim_id: claim for claim in case.claims}
        for claim in case.claims:
            claim_key = (case.case_id, claim.claim_id)
            annotated_claims.add(claim_key)
            annotated_links.update(
                (case.case_id, claim.claim_id, chunk_id)
                for chunk_id in claim.relevant_chunk_ids
            )

        for claim in predictions[case.case_id].claims:
            claim_key = (case.case_id, claim.claim_id)
            if claim.cited_chunk_ids and claim.claim_id in annotations:
                covered_claims.add(claim_key)
            predicted_links.update(
                (case.case_id, claim.claim_id, chunk_id)
                for chunk_id in claim.cited_chunk_ids
            )
            assessment = independent.get(claim_key)
            if assessment is not None:
                assessed_claims += 1
                unsupported_claims += int(not assessment.supported)

    correct_links = annotated_links.intersection(predicted_links)
    return RagCitationMetrics(
        citation_precision=(
            len(correct_links) / len(predicted_links) if predicted_links else 0.0
        ),
        citation_recall=(
            len(correct_links) / len(annotated_links) if annotated_links else 0.0
        ),
        citation_coverage=(
            len(covered_claims) / len(annotated_claims) if annotated_claims else 0.0
        ),
        unsupported_claim_rate=(
            unsupported_claims / assessed_claims if assessed_claims else 0.0
        ),
        annotated_claims=len(annotated_claims),
        assessed_claims=assessed_claims,
    )


def evaluate_rag(
    cases: Sequence[RagEvaluationCase],
    predictions: Sequence[RagEvaluationPrediction],
    *, assessments: Sequence[ClaimAssessment] = (),
) -> RagEvaluationReport:
    if len({case.case_id for case in cases}) != len(cases) or len({item.case_id for item in predictions}) != len(predictions):
        raise ValueError("duplicate evaluation case or prediction ID")
    independent = assessment_map(assessments)
    predicted_claims = {(item.case_id, claim.claim_id) for item in predictions for claim in item.claims}
    if set(independent).difference(predicted_claims):
        raise ValueError("independent assessment references an unknown predicted claim")
    prediction_by_id = {prediction.case_id: prediction for prediction in predictions}
    expected_ids = {case.case_id for case in cases}
    missing = expected_ids.difference(prediction_by_id)
    extra = set(prediction_by_id).difference(expected_ids)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing predictions: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unknown predictions: {', '.join(sorted(extra))}")
        raise ValueError("; ".join(details))

    evaluated: list[RagCaseEvaluation] = []
    category_counts: dict[str, int] = {}
    for case in cases:
        for category in set(case.categories):
            category_counts[category] = category_counts.get(category, 0) + 1
        prediction = prediction_by_id[case.case_id]
        grades = case.graded_relevance
        post_ranked = (
            prediction.post_rerank_chunk_ids
            if prediction.post_rerank_chunk_ids is not None
            else prediction.ranked_chunk_ids
        )
        evaluated.append(
            RagCaseEvaluation(
                case_id=case.case_id,
                recall_at_5=recall_at_k(prediction.ranked_chunk_ids, grades, 5),
                recall_at_10=recall_at_k(prediction.ranked_chunk_ids, grades, 10),
                recall_at_20=recall_at_k(prediction.ranked_chunk_ids, grades, 20),
                reciprocal_rank=reciprocal_rank(prediction.ranked_chunk_ids, grades),
                ndcg_at_10=ndcg_at_k(prediction.ranked_chunk_ids, grades, 10),
                pre_rerank_reciprocal_rank=reciprocal_rank(
                    prediction.pre_rerank_chunk_ids, grades
                ),
                pre_rerank_ndcg_at_10=ndcg_at_k(
                    prediction.pre_rerank_chunk_ids, grades, 10
                ),
                post_rerank_reciprocal_rank=reciprocal_rank(post_ranked, grades),
                post_rerank_ndcg_at_10=ndcg_at_k(post_ranked, grades, 10),
                no_answer_correct=(
                    not prediction.ranked_chunk_ids if case.no_answer else None
                ),
            )
        )

    answerable = [
        result
        for result, case in zip(evaluated, cases, strict=True)
        if not case.no_answer or case.answerability == "relevant_insufficient"
    ]
    no_answer_results = [
        result.no_answer_correct
        for result in evaluated
        if result.no_answer_correct is not None
    ]
    before_mrr = _average([result.pre_rerank_reciprocal_rank for result in answerable])
    after_mrr = _average([result.post_rerank_reciprocal_rank for result in answerable])
    before_ndcg = _average([result.pre_rerank_ndcg_at_10 for result in answerable])
    after_ndcg = _average([result.post_rerank_ndcg_at_10 for result in answerable])

    latency = [prediction_by_id[case.case_id].latency for case in cases]
    return RagEvaluationReport(
        total_cases=len(cases),
        category_counts=dict(sorted(category_counts.items())),
        retrieval=RagRetrievalMetrics(
            evaluated_cases=len(answerable),
            recall_at_5=_average([result.recall_at_5 for result in answerable]),
            recall_at_10=_average([result.recall_at_10 for result in answerable]),
            recall_at_20=_average([result.recall_at_20 for result in answerable]),
            mrr=_average([result.reciprocal_rank for result in answerable]),
            ndcg_at_10=_average([result.ndcg_at_10 for result in answerable]),
            no_answer_accuracy=(
                sum(bool(value) for value in no_answer_results) / len(no_answer_results)
                if no_answer_results
                else 0.0
            ),
            no_answer_cases=len(no_answer_results),
        ),
        reranker=RagRerankerComparison(
            mrr_before=before_mrr,
            mrr_after=after_mrr,
            mrr_delta=after_mrr - before_mrr,
            ndcg_at_10_before=before_ndcg,
            ndcg_at_10_after=after_ndcg,
            ndcg_at_10_delta=after_ndcg - before_ndcg,
        ),
        citations=_citation_metrics(cases, prediction_by_id, assessments),
        production=production_metrics(cases, prediction_by_id, assessments),
        performance=RagPerformanceMetrics(
            query_embedding_ms=_latency([item.query_embedding_ms for item in latency]),
            dense_search_ms=_latency([item.dense_search_ms for item in latency]),
            bm25_ms=_latency([item.bm25_ms for item in latency]),
            rerank_ms=_latency([item.rerank_ms for item in latency]),
            total_rag_ms=_latency([item.total_rag_ms for item in latency]),
        ),
        cases=evaluated,
    )


def production_metrics(cases, predictions, assessments=()) -> dict[str, Any]:
    def covers(observed, gold):
        return observed is not None and (
            observed.document_id == gold.document_id
            and observed.source_span.document_hash == gold.source_span.document_hash
            and observed.source_span.document_text_hash == gold.source_span.document_text_hash
            and observed.source_span.start_char <= gold.source_span.start_char
            and observed.source_span.end_char >= gold.source_span.end_char
        )

    rows = []
    for case in cases:
        prediction = predictions[case.case_id]
        relevant = set(case.graded_relevance)
        gold_spans = [span for span in case.gold_spans if span.relevance_grade > 0]
        evidence_gold = {span.span_id for span in gold_spans} if gold_spans else relevant
        expected_docs = set(case.gold_document_ids) | {span.document_id for span in gold_spans}
        row = {"case_id": case.case_id, "relevant_evidence_n": len(evidence_gold), "relevant_documents_n": len(expected_docs)}
        ranked = prediction.ranked_chunk_ids
        for k in (1, 5, 10):
            retrieved = ranked[:k]
            hits = set(retrieved) & relevant
            if gold_spans:
                hits = {gold.span_id for gold in gold_spans for key in retrieved
                        if covers(prediction.chunk_spans.get(key), gold)}
            hit_chunks = [key for key in retrieved if (
                any(covers(prediction.chunk_spans.get(key), gold) for gold in gold_spans)
                if gold_spans else key in relevant
            )]
            docs = {prediction.chunk_document_ids[key] for key in retrieved if key in prediction.chunk_document_ids}
            row[f"evidence_recall_at_{k}"] = len(hits)/len(evidence_gold) if evidence_gold else None
            row[f"document_recall_at_{k}"] = len(docs & expected_docs)/len(expected_docs) if expected_docs else None
            row[f"precision_at_{k}"] = len(hit_chunks)/k if evidence_gold else None
            row[f"hit_rate_at_{k}"] = float(bool(hits)) if evidence_gold else None
            complete_hits = hits if gold_spans else set(retrieved)
            row[f"complete_evidence_at_{k}"] = float(any(set(group).issubset(complete_hits) for group in case.evidence_sets)) if case.evidence_sets else None
        scope = set(case.expected_scope_document_ids)
        row["scope_violations"] = sum(
            1 for key in ranked if scope and prediction.chunk_document_ids.get(key) not in scope
        )
        rows.append(row)
    metrics = {}
    for name in (f"{metric}_at_{k}" for metric in ("evidence_recall", "document_recall", "precision", "hit_rate", "complete_evidence") for k in (1, 5, 10)):
        values = [row[name] for row in rows if row[name] is not None]
        metrics[name] = {"value": _average(values) if values else None, "n": len(values), "denominator": "macro over cases with applicable gold; precision divides by K"}
    metrics["scope_violations"] = sum(row["scope_violations"] for row in rows)
    metrics["independent_answer"] = {
        "n": len(assessments),
        "faithfulness": _average([float(item.supported) for item in assessments]) if assessments else None,
        "citation_accuracy": _average([float(item.citation_correct) for item in assessments]) if assessments else None,
        "status": "assessed" if assessments else "unassessed",
    }
    metrics["per_case"] = rows
    abstentions = [(case, predictions[case.case_id]) for case in cases if predictions[case.case_id].abstained is not None]
    answerable = [prediction for case, prediction in abstentions if case.answerability == "answerable" or (case.answerability is None and not case.no_answer)]
    unanswerable = [prediction for case, prediction in abstentions if case.answerability in {"absent", "relevant_insufficient"} or case.no_answer]
    metrics["abstention"] = {
        "answerable_n": len(answerable), "unanswerable_n": len(unanswerable),
        "false_abstention_rate": _average([float(item.abstained) for item in answerable]) if answerable else None,
        "correct_abstention_rate": _average([float(item.abstained) for item in unanswerable]) if unanswerable else None,
    }
    return metrics


__all__ = [
    "RagCaseEvaluation",
    "RagCitationMetrics",
    "RagEvaluationReport",
    "RagLatencyPercentiles",
    "RagPerformanceMetrics",
    "RagRerankerComparison",
    "RagRetrievalMetrics",
    "evaluate_rag",
    "ndcg_at_k",
    "percentile",
    "recall_at_k",
    "reciprocal_rank",
]
