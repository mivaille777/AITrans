from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CrossDocumentEvaluationExpectation:
    case_id: str
    fixture: str
    query: str
    expected_document_count: int | None = None
    min_agreement_count: int = 0
    max_agreement_count: int | None = None
    min_disagreement_count: int = 0
    max_disagreement_count: int | None = None
    min_claim_support_count: int = 0
    min_relation_support_count: int = 0


@dataclass(frozen=True, slots=True)
class CrossDocumentEvaluationResult:
    case_id: str
    passed: bool
    document_count: int
    agreement_count: int
    disagreement_count: int
    claim_support_count: int
    relation_support_count: int
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrossDocumentEvaluationBatchResult:
    total_cases: int
    passed_cases: int
    pass_rate: float
    agreement_case_rate: float
    disagreement_case_rate: float
    average_document_count: float
    results: tuple[CrossDocumentEvaluationResult, ...] = field(default_factory=tuple)


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def load_cross_document_evaluation_dataset(
    path: str | Path,
) -> tuple[CrossDocumentEvaluationExpectation, ...]:
    cases: list[CrossDocumentEvaluationExpectation] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Cross-document dataset line {line_number} must be an object.")
        case_id = str(payload.get("case_id", "") or "").strip()
        fixture = str(payload.get("fixture", "") or "").strip()
        query = str(payload.get("query", "") or "").strip()
        if not case_id or not fixture or not query:
            raise ValueError(
                f"Cross-document dataset line {line_number} requires case_id, fixture and query."
            )
        if case_id in seen:
            raise ValueError(f"Duplicate cross-document evaluation case_id: {case_id}")
        seen.add(case_id)
        raw_documents = payload.get("expected_document_count")
        raw_max_agreements = payload.get("max_agreement_count")
        raw_max_disagreements = payload.get("max_disagreement_count")
        cases.append(
            CrossDocumentEvaluationExpectation(
                case_id=case_id,
                fixture=fixture,
                query=query,
                expected_document_count=(
                    None
                    if raw_documents is None
                    else _nonnegative_int(raw_documents, 0)
                ),
                min_agreement_count=_nonnegative_int(
                    payload.get("min_agreement_count"), 0
                ),
                max_agreement_count=(
                    None
                    if raw_max_agreements is None
                    else _nonnegative_int(raw_max_agreements, 0)
                ),
                min_disagreement_count=_nonnegative_int(
                    payload.get("min_disagreement_count"), 0
                ),
                max_disagreement_count=(
                    None
                    if raw_max_disagreements is None
                    else _nonnegative_int(raw_max_disagreements, 0)
                ),
                min_claim_support_count=_nonnegative_int(
                    payload.get("min_claim_support_count"), 0
                ),
                min_relation_support_count=_nonnegative_int(
                    payload.get("min_relation_support_count"), 0
                ),
            )
        )
    return tuple(cases)


def evaluate_cross_document_case(
    expectation: CrossDocumentEvaluationExpectation,
    *,
    service: Any,
    workspace_id: str,
) -> CrossDocumentEvaluationResult:
    analysis = service.analyze(
        workspace_id=workspace_id,
        query=expectation.query,
    )
    failures: list[str] = []
    if (
        expectation.expected_document_count is not None
        and analysis.document_count != expectation.expected_document_count
    ):
        failures.append("document_count_mismatch")
    if analysis.agreement_count < expectation.min_agreement_count:
        failures.append("agreement_count_below_minimum")
    if (
        expectation.max_agreement_count is not None
        and analysis.agreement_count > expectation.max_agreement_count
    ):
        failures.append("agreement_count_above_maximum")
    if analysis.disagreement_count < expectation.min_disagreement_count:
        failures.append("disagreement_count_below_minimum")
    if (
        expectation.max_disagreement_count is not None
        and analysis.disagreement_count > expectation.max_disagreement_count
    ):
        failures.append("disagreement_count_above_maximum")
    if analysis.claim_support_count < expectation.min_claim_support_count:
        failures.append("claim_support_count_below_minimum")
    if analysis.relation_support_count < expectation.min_relation_support_count:
        failures.append("relation_support_count_below_minimum")

    for agreement in analysis.agreements:
        if len(set(agreement.document_ids)) < 2:
            failures.append("agreement_without_multiple_documents")
            break
    for disagreement in analysis.disagreements:
        if len(set(disagreement.document_ids)) < 2:
            failures.append("disagreement_without_multiple_documents")
            break
        if len(disagreement.alternatives) < 2:
            failures.append("disagreement_without_alternatives")
            break

    return CrossDocumentEvaluationResult(
        case_id=expectation.case_id,
        passed=not failures,
        document_count=analysis.document_count,
        agreement_count=analysis.agreement_count,
        disagreement_count=analysis.disagreement_count,
        claim_support_count=analysis.claim_support_count,
        relation_support_count=analysis.relation_support_count,
        failures=tuple(dict.fromkeys(failures)),
    )


def aggregate_cross_document_results(
    results: tuple[CrossDocumentEvaluationResult, ...],
) -> CrossDocumentEvaluationBatchResult:
    total = len(results)
    denominator = float(total or 1)
    passed = sum(item.passed for item in results)
    return CrossDocumentEvaluationBatchResult(
        total_cases=total,
        passed_cases=passed,
        pass_rate=round(passed / denominator, 4) if total else 0.0,
        agreement_case_rate=(
            round(sum(item.agreement_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        disagreement_case_rate=(
            round(sum(item.disagreement_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        average_document_count=(
            round(sum(item.document_count for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        results=results,
    )


__all__ = [
    "CrossDocumentEvaluationBatchResult",
    "CrossDocumentEvaluationExpectation",
    "CrossDocumentEvaluationResult",
    "aggregate_cross_document_results",
    "evaluate_cross_document_case",
    "load_cross_document_evaluation_dataset",
]
