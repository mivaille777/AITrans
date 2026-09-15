from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchMemoryEvaluationExpectation:
    case_id: str
    fixture: str
    query: str
    min_hit_count: int = 0
    max_hit_count: int | None = None
    min_groundable_hit_rate: float = 0.0
    max_groundable_hit_rate: float = 1.0
    min_provenance_resolution_rate: float = 0.0
    max_provenance_resolution_rate: float = 1.0
    min_fresh_hit_count: int = 0
    min_legacy_unknown_hit_count: int = 0
    min_stale_hit_count: int = 0
    min_orphaned_hit_count: int = 0
    min_detached_hit_count: int = 0
    min_conflicted_hit_count: int = 0
    require_conflict: bool | None = None
    expected_conflict_group_count: int | None = None


@dataclass(frozen=True, slots=True)
class ResearchMemoryEvaluationResult:
    case_id: str
    passed: bool
    hit_count: int
    groundable_hit_rate: float
    provenance_resolution_rate: float
    conflict_hit_rate: float
    stale_hit_rate: float
    orphaned_hit_rate: float
    detached_hit_rate: float
    fresh_hit_count: int
    legacy_unknown_hit_count: int
    stale_hit_count: int
    orphaned_hit_count: int
    detached_hit_count: int
    conflicted_hit_count: int
    conflict_group_count: int
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchMemoryEvaluationBatchResult:
    total_cases: int
    passed_cases: int
    pass_rate: float
    average_groundable_hit_rate: float
    average_provenance_resolution_rate: float
    conflict_case_rate: float
    stale_case_rate: float
    orphaned_case_rate: float
    detached_case_rate: float
    results: tuple[ResearchMemoryEvaluationResult, ...] = field(default_factory=tuple)


def _bounded_rate(value: object, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def load_research_memory_evaluation_dataset(
    path: str | Path,
) -> tuple[ResearchMemoryEvaluationExpectation, ...]:
    dataset_path = Path(path)
    cases: list[ResearchMemoryEvaluationExpectation] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Research-memory dataset line {line_number} must be an object.")
        case_id = str(payload.get("case_id", "")).strip()
        fixture = str(payload.get("fixture", "")).strip()
        query = str(payload.get("query", "")).strip()
        if not case_id or not fixture or not query:
            raise ValueError(
                f"Research-memory dataset line {line_number} requires case_id, fixture and query."
            )
        if case_id in seen:
            raise ValueError(f"Duplicate research-memory evaluation case_id: {case_id}")
        seen.add(case_id)
        raw_max_hits = payload.get("max_hit_count")
        raw_conflict_count = payload.get("expected_conflict_group_count")
        raw_require_conflict = payload.get("require_conflict")
        cases.append(
            ResearchMemoryEvaluationExpectation(
                case_id=case_id,
                fixture=fixture,
                query=query,
                min_hit_count=_nonnegative_int(payload.get("min_hit_count"), 0),
                max_hit_count=(
                    None if raw_max_hits is None else _nonnegative_int(raw_max_hits, 0)
                ),
                min_groundable_hit_rate=_bounded_rate(
                    payload.get("min_groundable_hit_rate"), 0.0
                ),
                max_groundable_hit_rate=_bounded_rate(
                    payload.get("max_groundable_hit_rate"), 1.0
                ),
                min_provenance_resolution_rate=_bounded_rate(
                    payload.get("min_provenance_resolution_rate"), 0.0
                ),
                max_provenance_resolution_rate=_bounded_rate(
                    payload.get("max_provenance_resolution_rate"), 1.0
                ),
                min_fresh_hit_count=_nonnegative_int(payload.get("min_fresh_hit_count"), 0),
                min_legacy_unknown_hit_count=_nonnegative_int(
                    payload.get("min_legacy_unknown_hit_count"), 0
                ),
                min_stale_hit_count=_nonnegative_int(payload.get("min_stale_hit_count"), 0),
                min_orphaned_hit_count=_nonnegative_int(
                    payload.get("min_orphaned_hit_count"), 0
                ),
                min_detached_hit_count=_nonnegative_int(
                    payload.get("min_detached_hit_count"), 0
                ),
                min_conflicted_hit_count=_nonnegative_int(
                    payload.get("min_conflicted_hit_count"), 0
                ),
                require_conflict=(
                    None if raw_require_conflict is None else bool(raw_require_conflict)
                ),
                expected_conflict_group_count=(
                    None
                    if raw_conflict_count is None
                    else _nonnegative_int(raw_conflict_count, 0)
                ),
            )
        )
    return tuple(cases)


def evaluate_research_memory_case(
    expectation: ResearchMemoryEvaluationExpectation,
    *,
    service: Any,
    workspace_id: str,
) -> ResearchMemoryEvaluationResult:
    reliable = tuple(
        service.search_reliable(
            workspace_id=workspace_id,
            query=expectation.query,
            limit=50,
        )
    )
    summary = service.reliability_summary(reliable)
    conflicts = tuple(service.conflict_groups(workspace_id=workspace_id))
    failures: list[str] = []

    if summary.total_hit_count < expectation.min_hit_count:
        failures.append("hit_count_below_minimum")
    if (
        expectation.max_hit_count is not None
        and summary.total_hit_count > expectation.max_hit_count
    ):
        failures.append("hit_count_above_maximum")
    if summary.groundable_hit_rate < expectation.min_groundable_hit_rate:
        failures.append("groundable_hit_rate_below_minimum")
    if summary.groundable_hit_rate > expectation.max_groundable_hit_rate:
        failures.append("groundable_hit_rate_above_maximum")
    if summary.provenance_resolution_rate < expectation.min_provenance_resolution_rate:
        failures.append("provenance_resolution_rate_below_minimum")
    if summary.provenance_resolution_rate > expectation.max_provenance_resolution_rate:
        failures.append("provenance_resolution_rate_above_maximum")
    if summary.fresh_hit_count < expectation.min_fresh_hit_count:
        failures.append("fresh_hit_count_below_minimum")
    if summary.legacy_unknown_hit_count < expectation.min_legacy_unknown_hit_count:
        failures.append("legacy_unknown_hit_count_below_minimum")
    if summary.stale_hit_count < expectation.min_stale_hit_count:
        failures.append("stale_hit_count_below_minimum")
    if summary.orphaned_hit_count < expectation.min_orphaned_hit_count:
        failures.append("orphaned_hit_count_below_minimum")
    if summary.detached_hit_count < expectation.min_detached_hit_count:
        failures.append("detached_hit_count_below_minimum")
    if summary.conflicted_hit_count < expectation.min_conflicted_hit_count:
        failures.append("conflicted_hit_count_below_minimum")
    if expectation.require_conflict is True and not conflicts:
        failures.append("expected_conflict_missing")
    if expectation.require_conflict is False and conflicts:
        failures.append("unexpected_conflict")
    if (
        expectation.expected_conflict_group_count is not None
        and len(conflicts) != expectation.expected_conflict_group_count
    ):
        failures.append("conflict_group_count_mismatch")

    return ResearchMemoryEvaluationResult(
        case_id=expectation.case_id,
        passed=not failures,
        hit_count=summary.total_hit_count,
        groundable_hit_rate=round(summary.groundable_hit_rate, 4),
        provenance_resolution_rate=round(summary.provenance_resolution_rate, 4),
        conflict_hit_rate=round(summary.conflict_hit_rate, 4),
        stale_hit_rate=round(summary.stale_hit_rate, 4),
        orphaned_hit_rate=round(summary.orphaned_hit_rate, 4),
        detached_hit_rate=round(summary.detached_hit_rate, 4),
        fresh_hit_count=summary.fresh_hit_count,
        legacy_unknown_hit_count=summary.legacy_unknown_hit_count,
        stale_hit_count=summary.stale_hit_count,
        orphaned_hit_count=summary.orphaned_hit_count,
        detached_hit_count=summary.detached_hit_count,
        conflicted_hit_count=summary.conflicted_hit_count,
        conflict_group_count=len(conflicts),
        failures=tuple(failures),
    )


def aggregate_research_memory_results(
    results: tuple[ResearchMemoryEvaluationResult, ...],
) -> ResearchMemoryEvaluationBatchResult:
    total = len(results)
    denominator = float(total or 1)
    passed = sum(item.passed for item in results)
    return ResearchMemoryEvaluationBatchResult(
        total_cases=total,
        passed_cases=passed,
        pass_rate=round(passed / denominator, 4) if total else 0.0,
        average_groundable_hit_rate=(
            round(sum(item.groundable_hit_rate for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        average_provenance_resolution_rate=(
            round(
                sum(item.provenance_resolution_rate for item in results) / denominator,
                4,
            )
            if total
            else 0.0
        ),
        conflict_case_rate=(
            round(sum(item.conflict_group_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        stale_case_rate=(
            round(sum(item.stale_hit_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        orphaned_case_rate=(
            round(sum(item.orphaned_hit_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        detached_case_rate=(
            round(sum(item.detached_hit_count > 0 for item in results) / denominator, 4)
            if total
            else 0.0
        ),
        results=results,
    )


__all__ = [
    "ResearchMemoryEvaluationBatchResult",
    "ResearchMemoryEvaluationExpectation",
    "ResearchMemoryEvaluationResult",
    "aggregate_research_memory_results",
    "evaluate_research_memory_case",
    "load_research_memory_evaluation_dataset",
]
