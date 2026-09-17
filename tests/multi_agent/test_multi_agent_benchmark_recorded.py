from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.evaluation.multi_agent_benchmark import BenchmarkBudget, MultiAgentBenchmarkCase
from backend.evaluation.multi_agent_benchmark_recorded import RecordedBenchmarkRunner


def _case() -> MultiAgentBenchmarkCase:
    return MultiAgentBenchmarkCase(
        case_id="T35",
        split="heldout",
        stages=("MA10",),
        category="ab_evaluation",
        prompt="compare",
        fixture_refs=(),
        hard_assertions=("quality reported",),
        score_dimensions=("completion",),
    )


def test_recorded_runner_loads_explicit_observation(tmp_path: Path) -> None:
    path = tmp_path / "observations.json"
    path.write_text(
        json.dumps(
            {
                "observations": [
                    {
                        "case_id": "T35",
                        "strategy": "multi_agent",
                        "budget_mode": "equal_token",
                        "completed": True,
                        "hard_assertion_results": {"quality reported": True},
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "versions": {"model_name": "qwen-test", "git_commit": "abc"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = RecordedBenchmarkRunner.from_json(path)
    observation = runner(
        _case(),
        strategy="multi_agent",
        environment="qwen3_local",
        budget=BenchmarkBudget(mode="equal_token", token_limit=100),
    )

    assert observation.total_tokens == 20
    assert observation.versions.model_name == "qwen-test"


def test_recorded_runner_fails_closed_when_measurement_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "observations.json"
    path.write_text("[]", encoding="utf-8")
    runner = RecordedBenchmarkRunner.from_json(path)

    with pytest.raises(ValueError, match="missing recorded observation"):
        runner(
            _case(),
            strategy="single_agent",
            environment="configured_llm",
            budget=BenchmarkBudget(mode="production"),
        )


def test_recorded_runner_rejects_duplicate_measurements(tmp_path: Path) -> None:
    item = {
        "case_id": "T35",
        "strategy": "multi_agent",
        "budget_mode": "production",
        "completed": True,
    }
    path = tmp_path / "observations.json"
    path.write_text(json.dumps([item, item]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate recorded observation"):
        RecordedBenchmarkRunner.from_json(path)
