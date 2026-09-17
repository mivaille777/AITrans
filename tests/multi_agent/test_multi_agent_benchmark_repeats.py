from __future__ import annotations

import pytest

from backend.evaluation.multi_agent_benchmark import BenchmarkObservation, BenchmarkVersionInfo
from backend.evaluation.multi_agent_benchmark_repeats import (
    RepeatedBenchmarkObservation,
    aggregate_repeated_observations,
)


def _record(repeat: int, *, latency: float, tokens: int, version: str = "v1", assertion: bool = True):
    return RepeatedBenchmarkObservation(
        case_id="T35",
        strategy="multi_agent",
        budget_mode="equal_token",
        repeat=repeat,
        observation=BenchmarkObservation(
            completed=True,
            dimension_scores={"completion": 1.0, "source_support": 0.8 + 0.05 * repeat},
            hard_assertion_results={"quality reported": assertion},
            source_coverage=0.9,
            prompt_tokens=tokens - 10,
            completion_tokens=10,
            model_calls=2,
            tool_calls=3,
            retrieval_calls=1,
            latency_ms=latency,
            versions=BenchmarkVersionInfo(model_name="qwen", model_version=version, git_commit="abc"),
        ),
    )


def test_three_repeats_are_aggregated_with_fluctuation_metadata() -> None:
    result = aggregate_repeated_observations(
        [_record(1, latency=10, tokens=100), _record(2, latency=20, tokens=120), _record(3, latency=30, tokens=140)]
    )
    item = result[("T35", "multi_agent", "equal_token")]

    assert item.latency_ms == 20
    assert item.total_tokens == 120
    assert item.metadata["repeat_count"] == 3
    assert item.metadata["latency_ms_samples"] == [10.0, 20.0, 30.0]
    assert item.metadata["latency_ms_pstdev"] > 0
    assert item.hard_assertion_results["quality reported"] is True


def test_hard_assertion_must_pass_on_every_repeat() -> None:
    result = aggregate_repeated_observations(
        [
            _record(1, latency=10, tokens=100),
            _record(2, latency=10, tokens=100, assertion=False),
            _record(3, latency=10, tokens=100),
        ]
    )
    assert result[("T35", "multi_agent", "equal_token")].hard_assertion_results == {"quality reported": False}


def test_version_drift_across_repeats_is_rejected() -> None:
    with pytest.raises(ValueError, match="versions changed"):
        aggregate_repeated_observations(
            [
                _record(1, latency=10, tokens=100, version="v1"),
                _record(2, latency=10, tokens=100, version="v2"),
                _record(3, latency=10, tokens=100, version="v1"),
            ]
        )


def test_less_than_three_repeats_is_not_a_real_provider_result() -> None:
    with pytest.raises(ValueError, match="at least 3 repeats"):
        aggregate_repeated_observations(
            [_record(1, latency=10, tokens=100), _record(2, latency=10, tokens=100)]
        )
