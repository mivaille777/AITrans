from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.evaluation.multi_agent_benchmark import (
    BenchmarkBudget,
    BenchmarkObservation,
    BenchmarkVersionInfo,
    MultiAgentBenchmarkCase,
    load_multi_agent_evaluation_cases,
    run_multi_agent_benchmark,
    write_multi_agent_benchmark_report,
)

PRODUCTION_BUDGETS = {
    "single_agent": BenchmarkBudget(mode="production", token_limit=600, model_call_limit=2, tool_call_limit=4, retrieval_call_limit=2, deadline_ms=5000),
    "legacy_collaboration": BenchmarkBudget(mode="production", token_limit=900, model_call_limit=4, tool_call_limit=6, retrieval_call_limit=3, deadline_ms=5000),
    "multi_agent": BenchmarkBudget(mode="production", token_limit=1200, model_call_limit=5, tool_call_limit=8, retrieval_call_limit=4, deadline_ms=5000),
}


def _case() -> MultiAgentBenchmarkCase:
    return MultiAgentBenchmarkCase(
        case_id="T35",
        split="heldout",
        stages=("MA10",),
        category="ab_evaluation",
        prompt="compare strategies",
        fixture_refs=("paper-a", "paper-b"),
        hard_assertions=("quality reported", "cost reported"),
        score_dimensions=("completion", "source_support", "latency", "cost"),
    )


def _passing_runner(case, *, strategy, environment, budget):
    assert environment == "deterministic"
    return BenchmarkObservation(
        completed=True,
        dimension_scores={"completion": 1.0, "source_support": 0.9, "latency": 0.8, "cost": 0.7},
        hard_assertion_results={assertion: True for assertion in case.hard_assertions},
        source_coverage=0.75,
        prompt_tokens=200,
        completion_tokens=100,
        model_calls=1,
        tool_calls=2,
        retrieval_calls=1,
        latency_ms=25.0,
        versions=BenchmarkVersionInfo(git_commit="abc", graph_version="ma10-test", model_name="fake"),
        metadata={"strategy_seen": strategy, "budget_mode": budget.mode},
    )


def test_loads_frozen_ma_cases_and_preserves_ma10_contract() -> None:
    path = Path(__file__).with_name("evaluation_cases.json")
    cases = load_multi_agent_evaluation_cases(path)

    assert len(cases) == 36
    t35 = next(case for case in cases if case.case_id == "T35")
    assert t35.stages == ("MA10",)
    assert t35.split == "heldout"
    assert "source_support" in t35.score_dimensions
    assert "no benefit claim based on role count" in t35.hard_assertions


def test_runs_three_strategies_under_production_and_equal_token_budgets() -> None:
    report = run_multi_agent_benchmark(
        [_case()],
        runner=_passing_runner,
        environment="deterministic",
        production_budgets=PRODUCTION_BUDGETS,
        equal_token_limit=400,
    )

    assert report.schema_version == "ma10-benchmark-v1"
    assert len(report.tasks) == 6
    equal = [task for task in report.tasks if task.budget.mode == "equal_token"]
    assert {task.budget.token_limit for task in equal} == {400}
    production = {task.strategy: task.budget.token_limit for task in report.tasks if task.budget.mode == "production"}
    assert production == {"single_agent": 600, "legacy_collaboration": 900, "multi_agent": 1200}
    assert all(task.passed for task in report.tasks)
    assert report.release_ready is True


def test_budget_exhaustion_is_visible_and_fails_the_case() -> None:
    def over_budget(case, *, strategy, environment, budget):
        del strategy, environment
        return BenchmarkObservation(
            completed=True,
            hard_assertion_results={assertion: True for assertion in case.hard_assertions},
            prompt_tokens=budget.token_limit,
            completion_tokens=1,
        )

    report = run_multi_agent_benchmark(
        [_case()],
        runner=over_budget,
        environment="deterministic",
        production_budgets=PRODUCTION_BUDGETS,
        equal_token_limit=300,
        strategies=("single_agent",),
        budget_modes=("equal_token",),
    )

    task = report.tasks[0]
    assert task.passed is False
    assert task.budget_violations == ("token_budget_exceeded",)
    assert report.release_ready is False


@pytest.mark.parametrize(
    "violation",
    [
        "scope_leak",
        "fabricated_experiment",
        "fabricated_reference",
        "silent_note_overwrite",
        "deleted_data_resurrection",
        "duplicate_business_write",
    ],
)
def test_release_blockers_cannot_be_averaged_away(violation: str) -> None:
    def unsafe(case, *, strategy, environment, budget):
        del strategy, environment, budget
        return BenchmarkObservation(
            completed=True,
            dimension_scores={dimension: 1.0 for dimension in case.score_dimensions},
            hard_assertion_results={assertion: True for assertion in case.hard_assertions},
            source_coverage=1.0,
            safety_violations=(violation,),
        )

    report = run_multi_agent_benchmark(
        [_case()],
        runner=unsafe,
        environment="deterministic",
        production_budgets=PRODUCTION_BUDGETS,
        equal_token_limit=300,
        strategies=("multi_agent",),
        budget_modes=("production",),
    )

    assert report.tasks[0].release_blockers == (violation,)
    assert report.release_ready is False
    assert any(violation in blocker for blocker in report.release_blockers)


def test_report_json_is_stable_and_records_unverified_real_surfaces(tmp_path: Path) -> None:
    report = run_multi_agent_benchmark(
        [_case()],
        runner=_passing_runner,
        environment="deterministic",
        production_budgets=PRODUCTION_BUDGETS,
        equal_token_limit=400,
        strategies=("single_agent", "multi_agent"),
        budget_modes=("production",),
        unverified_surfaces=("qwen3_local", "configured_llm", "manual_ui"),
        metadata={"host": "test"},
    )

    destination = write_multi_agent_benchmark_report(report, tmp_path / "ma10.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "ma10-benchmark-v1"
    assert payload["unverified_surfaces"] == ["qwen3_local", "configured_llm", "manual_ui"]
    assert payload["release_ready"] is False
    assert json.loads(report.to_json()) == payload


def test_equal_token_mode_requires_a_positive_shared_cap() -> None:
    with pytest.raises(ValueError, match="equal_token_limit"):
        run_multi_agent_benchmark(
            [_case()],
            runner=_passing_runner,
            environment="deterministic",
            production_budgets=PRODUCTION_BUDGETS,
            equal_token_limit=0,
        )


def test_unknown_usage_is_serialized_as_null_not_zero(tmp_path: Path) -> None:
    def contract_only(case, **_kwargs):
        return BenchmarkObservation(
            completed=True,
            hard_assertion_results={assertion: True for assertion in case.hard_assertions},
            metadata={"usage_measurement": "unavailable"},
        )

    report = run_multi_agent_benchmark(
        [_case()],
        runner=contract_only,
        environment="deterministic",
        production_budgets=PRODUCTION_BUDGETS,
        equal_token_limit=300,
        strategies=("multi_agent",),
        budget_modes=("production",),
    )
    payload = json.loads(report.to_json())

    assert payload["tasks"][0]["total_tokens"] is None
    assert payload["tasks"][0]["model_calls"] is None
    assert payload["summaries"][0]["mean_total_tokens"] is None
