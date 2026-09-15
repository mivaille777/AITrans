from __future__ import annotations

from dataclasses import replace
import json

import pytest

from backend.evaluation.dataset import load_evaluation_dataset, write_evaluation_dataset
from backend.evaluation.quality_gate import (
    evaluate_regression_quality,
    load_quality_thresholds,
)
from backend.evaluation.regression_fixture import load_regression_fixture
from backend.evaluation.runner import evaluate_agent_batch

DATASET = "backend/evaluation/datasets/regression.jsonl"
FIXTURE = "backend/evaluation/fixtures/regression_traces.json"
THRESHOLDS = "backend/evaluation/datasets/regression_quality_gate.json"


def _benchmark():
    cases = load_evaluation_dataset(DATASET)
    fixture = load_regression_fixture(FIXTURE)
    batch = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: fixture.get_run(case.case_id),
        resolve_events=fixture.get_events,
    )
    return cases, fixture, batch


def test_regression_dataset_and_fixture_are_aligned_and_pass() -> None:
    cases, fixture, batch = _benchmark()

    assert len(cases) == 8
    assert tuple(case.case_id for case in cases) == tuple(
        case.case_id for case in fixture.cases
    )
    assert batch.total_cases == 8
    assert batch.passed_cases == 8
    assert batch.pass_rate == 1.0
    assert batch.fallback_accuracy == 1.0
    assert batch.evidence_gate_accuracy == 1.0
    assert batch.trajectory_case_count == 8
    assert batch.react_run_rate == 0.375
    assert batch.grounded_rate == 0.25
    assert batch.grounding_verification_run_rate == 0.25
    assert batch.grounding_verification_pass_rate == 0.5
    assert batch.grounding_verification_fallback_rate == 0.5
    assert batch.retrieval_fallback_run_rate == 0.125
    assert batch.confirmation_guard_rate == 1.0
    assert batch.redundant_action_rate == 0.0
    assert batch.react_limit_rate == 0.0


def test_regression_quality_gate_passes_and_detects_coverage_regression() -> None:
    _cases, _fixture, batch = _benchmark()
    thresholds = load_quality_thresholds(THRESHOLDS)

    result = evaluate_regression_quality(batch, thresholds)
    assert result.passed is True
    assert result.failures == ()

    stricter = replace(thresholds, min_react_run_rate=0.5)
    failed = evaluate_regression_quality(batch, stricter)
    assert failed.passed is False
    assert failed.checks["react_run_rate"] is False
    assert any("react_run_rate" in failure for failure in failed.failures)


def test_negative_grounding_case_passes_only_with_safe_fallback() -> None:
    _cases, _fixture, batch = _benchmark()
    result = next(
        item
        for item in batch.results
        if item.case_id == "grounding-verification-fallback"
    )

    assert result.passed is True
    assert result.grounding_verification_pass is True
    assert result.trajectory.final_grounding_verification_passed is False
    assert result.trajectory.final_grounding_fallback_applied is True
    assert result.trajectory.unsupported_claim_count == 1


def test_timeout_case_is_a_passing_safe_failure_contract() -> None:
    _cases, _fixture, batch = _benchmark()
    result = next(
        item for item in batch.results if item.case_id == "tool-timeout-safe-failure"
    )

    assert result.passed is True
    assert result.status_match is True
    assert result.fallback_match is True
    assert result.failure_pass is True


def test_regression_dataset_round_trip_preserves_new_expectations(tmp_path) -> None:
    cases = load_evaluation_dataset(DATASET)
    target = tmp_path / "regression.jsonl"

    write_evaluation_dataset(target, cases)
    loaded = load_evaluation_dataset(target)

    assert loaded == cases
    fallback_case = next(
        case for case in loaded if case.case_id == "grounding-verification-fallback"
    )
    assert fallback_case.expected_grounding_verification_pass is False
    rag_case = next(case for case in loaded if case.case_id == "agentic-rag-refine-stop")
    assert rag_case.expected_final_evidence_gate_action == "stop"


def test_regression_fixture_rejects_non_contiguous_event_sequence(tmp_path) -> None:
    payload = json.loads(open(FIXTURE, encoding="utf-8").read())
    payload["cases"][0]["events"][1]["sequence"] = 4
    target = tmp_path / "broken.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="contiguous"):
        load_regression_fixture(target)
