from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from backend.evaluation.multi_agent_benchmark import (
    BenchmarkObservation,
    BenchmarkStrategy,
    BenchmarkVersionInfo,
)


@dataclass(frozen=True, slots=True)
class RepeatedBenchmarkObservation:
    case_id: str
    strategy: BenchmarkStrategy
    budget_mode: str
    repeat: int
    observation: BenchmarkObservation


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pstdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _complete_samples(values: Iterable[int | None], expected: int) -> list[float] | None:
    samples = [float(value) for value in values if value is not None]
    return samples if len(samples) == expected else None


def _version_key(version: BenchmarkVersionInfo) -> tuple[str, ...]:
    return (
        version.git_commit,
        version.graph_version,
        version.schema_version,
        version.model_provider,
        version.model_name,
        version.model_version,
        version.retrieval_version,
    )


def aggregate_repeated_observations(
    records: Iterable[RepeatedBenchmarkObservation],
    *,
    minimum_repeats: int = 3,
) -> dict[tuple[str, str, str], BenchmarkObservation]:
    if minimum_repeats < 1:
        raise ValueError("minimum_repeats must be >= 1")
    groups: dict[tuple[str, str, str], list[RepeatedBenchmarkObservation]] = {}
    for record in records:
        key = (record.case_id, record.strategy, record.budget_mode)
        groups.setdefault(key, []).append(record)

    result: dict[tuple[str, str, str], BenchmarkObservation] = {}
    for key, items in groups.items():
        repeat_ids = {item.repeat for item in items}
        if len(repeat_ids) != len(items):
            raise ValueError(f"duplicate repeat index for {key}")
        if len(items) < minimum_repeats:
            raise ValueError(
                f"{key} requires at least {minimum_repeats} repeats; found {len(items)}"
            )
        version_keys = {_version_key(item.observation.versions) for item in items}
        if len(version_keys) != 1:
            raise ValueError(f"model/runtime versions changed across repeats for {key}")

        dimensions = sorted(
            {dimension for item in items for dimension in item.observation.dimension_scores}
        )
        assertions = sorted(
            {assertion for item in items for assertion in item.observation.hard_assertion_results}
        )
        latency_samples = [float(item.observation.latency_ms) for item in items]
        token_samples = _complete_samples(
            (item.observation.total_tokens for item in items), len(items)
        )
        prompt_samples = _complete_samples(
            (item.observation.prompt_tokens for item in items), len(items)
        )
        completion_samples = _complete_samples(
            (item.observation.completion_tokens for item in items), len(items)
        )
        model_call_samples = _complete_samples(
            (item.observation.model_calls for item in items), len(items)
        )
        tool_call_samples = _complete_samples(
            (item.observation.tool_calls for item in items), len(items)
        )
        retrieval_call_samples = _complete_samples(
            (item.observation.retrieval_calls for item in items), len(items)
        )
        coverage_samples = [
            float(item.observation.source_coverage)
            for item in items
            if item.observation.source_coverage is not None
        ]
        dimension_samples = {
            dimension: [
                float(item.observation.dimension_scores[dimension])
                for item in items
                if dimension in item.observation.dimension_scores
            ]
            for dimension in dimensions
        }
        safety = tuple(
            sorted(
                {
                    violation
                    for item in items
                    for violation in item.observation.safety_violations
                }
            )
        )
        degradation_reasons = tuple(
            sorted(
                {
                    reason
                    for item in items
                    for reason in item.observation.degradation_reasons
                }
            )
        )
        failure_codes = [
            item.observation.failure_code for item in items if item.observation.failure_code
        ]
        result[key] = BenchmarkObservation(
            completed=all(item.observation.completed for item in items),
            dimension_scores={
                dimension: _mean(samples) for dimension, samples in dimension_samples.items()
            },
            hard_assertion_results={
                assertion: all(
                    item.observation.hard_assertion_results.get(assertion, False)
                    for item in items
                )
                for assertion in assertions
            },
            source_coverage=(
                _mean(coverage_samples) if len(coverage_samples) == len(items) else None
            ),
            prompt_tokens=round(_mean(prompt_samples)) if prompt_samples is not None else None,
            completion_tokens=(
                round(_mean(completion_samples))
                if completion_samples is not None
                else None
            ),
            model_calls=(
                round(_mean(model_call_samples))
                if model_call_samples is not None
                else None
            ),
            tool_calls=(
                round(_mean(tool_call_samples))
                if tool_call_samples is not None
                else None
            ),
            retrieval_calls=(
                round(_mean(retrieval_call_samples))
                if retrieval_call_samples is not None
                else None
            ),
            latency_ms=_mean(latency_samples),
            degraded=any(item.observation.degraded for item in items),
            degradation_reasons=degradation_reasons,
            failure_code=failure_codes[0] if failure_codes else "",
            safety_violations=safety,
            versions=items[0].observation.versions,
            metadata={
                "repeat_count": len(items),
                "repeat_ids": sorted(repeat_ids),
                "latency_ms_samples": latency_samples,
                "latency_ms_pstdev": _pstdev(latency_samples),
                "total_token_samples": token_samples,
                "total_token_pstdev": (
                    _pstdev(token_samples) if token_samples is not None else None
                ),
                "dimension_score_pstdev": {
                    dimension: _pstdev(samples)
                    for dimension, samples in dimension_samples.items()
                },
            },
        )
    return result


__all__ = ["RepeatedBenchmarkObservation", "aggregate_repeated_observations"]
