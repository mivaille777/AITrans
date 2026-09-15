from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEvaluationExpectation:
    case_id: str
    fixture: str
    capture_query: str
    query: str
    expected_entry_count: int
    expected_supported_count: int = 0
    expected_contested_count: int = 0
    expected_insufficient_count: int = 0
    expected_stale_count: int = 0


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEvaluationResult:
    case_id: str
    passed: bool
    entry_count: int
    supported_count: int
    contested_count: int
    insufficient_count: int
    stale_count: int
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEvaluationBatchResult:
    total_cases: int
    passed_cases: int
    pass_rate: float
    supported_case_rate: float
    contested_case_rate: float
    stale_case_rate: float
    results: tuple[EvidenceLedgerEvaluationResult, ...] = field(default_factory=tuple)


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def load_evidence_ledger_evaluation_dataset(
    path: str | Path,
) -> tuple[EvidenceLedgerEvaluationExpectation, ...]:
    cases: list[EvidenceLedgerEvaluationExpectation] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Evidence Ledger dataset line {line_number} must be an object.")
        case_id = str(payload.get("case_id", "") or "").strip()
        fixture = str(payload.get("fixture", "") or "").strip()
        capture_query = str(payload.get("capture_query", "") or "").strip()
        query = str(payload.get("query", "") or "").strip()
        if not case_id or not fixture or not capture_query:
            raise ValueError(
                f"Evidence Ledger dataset line {line_number} requires case_id, fixture and capture_query."
            )
        if case_id in seen:
            raise ValueError(f"Duplicate Evidence Ledger evaluation case_id: {case_id}")
        seen.add(case_id)
        cases.append(
            EvidenceLedgerEvaluationExpectation(
                case_id=case_id,
                fixture=fixture,
                capture_query=capture_query,
                query=query,
                expected_entry_count=_nonnegative_int(payload.get("expected_entry_count"), 0),
                expected_supported_count=_nonnegative_int(payload.get("expected_supported_count"), 0),
                expected_contested_count=_nonnegative_int(payload.get("expected_contested_count"), 0),
                expected_insufficient_count=_nonnegative_int(payload.get("expected_insufficient_count"), 0),
                expected_stale_count=_nonnegative_int(payload.get("expected_stale_count"), 0),
            )
        )
    return tuple(cases)


def evaluate_evidence_ledger_case(
    expectation: EvidenceLedgerEvaluationExpectation,
    *,
    service: Any,
    workspace_id: str,
) -> EvidenceLedgerEvaluationResult:
    snapshot = service.snapshot(
        workspace_id=workspace_id,
        query=expectation.query,
        limit=100,
    )
    actual = {
        "entry_count": snapshot.entry_count,
        "supported_count": snapshot.supported_count,
        "contested_count": snapshot.contested_count,
        "insufficient_count": snapshot.insufficient_count,
        "stale_count": snapshot.stale_count,
    }
    expected = {
        "entry_count": expectation.expected_entry_count,
        "supported_count": expectation.expected_supported_count,
        "contested_count": expectation.expected_contested_count,
        "insufficient_count": expectation.expected_insufficient_count,
        "stale_count": expectation.expected_stale_count,
    }
    failures = [
        f"{name}_mismatch"
        for name, value in actual.items()
        if value != expected[name]
    ]
    if sum(
        (
            snapshot.supported_count,
            snapshot.contested_count,
            snapshot.insufficient_count,
            snapshot.stale_count,
        )
    ) != snapshot.entry_count:
        failures.append("status_partition_mismatch")

    return EvidenceLedgerEvaluationResult(
        case_id=expectation.case_id,
        passed=not failures,
        entry_count=snapshot.entry_count,
        supported_count=snapshot.supported_count,
        contested_count=snapshot.contested_count,
        insufficient_count=snapshot.insufficient_count,
        stale_count=snapshot.stale_count,
        failures=tuple(failures),
    )


def aggregate_evidence_ledger_results(
    results: tuple[EvidenceLedgerEvaluationResult, ...],
) -> EvidenceLedgerEvaluationBatchResult:
    total = len(results)
    denominator = float(total or 1)
    passed = sum(item.passed for item in results)
    return EvidenceLedgerEvaluationBatchResult(
        total_cases=total,
        passed_cases=passed,
        pass_rate=round(passed / denominator, 4) if total else 0.0,
        supported_case_rate=(
            round(sum(item.supported_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        contested_case_rate=(
            round(sum(item.contested_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        stale_case_rate=(
            round(sum(item.stale_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        results=results,
    )


__all__ = [
    "EvidenceLedgerEvaluationBatchResult",
    "EvidenceLedgerEvaluationExpectation",
    "EvidenceLedgerEvaluationResult",
    "aggregate_evidence_ledger_results",
    "evaluate_evidence_ledger_case",
    "load_evidence_ledger_evaluation_dataset",
]
