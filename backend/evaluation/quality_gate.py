from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.evaluation.runner import AgentEvaluationBatchResult


@dataclass(frozen=True, slots=True)
class AgentRegressionQualityThresholds:
    min_total_cases: int = 1
    min_pass_rate: float = 1.0
    min_intent_accuracy: float = 0.0
    min_tool_accuracy: float = 0.0
    min_task_completion_rate: float = 0.0
    min_trajectory_case_rate: float = 1.0
    min_react_run_rate: float = 0.0
    min_grounded_rate: float = 0.0
    min_grounding_verification_run_rate: float = 0.0
    min_confirmation_guard_rate: float = 1.0
    min_fallback_accuracy: float = 1.0
    min_evidence_gate_accuracy: float = 1.0
    min_token_usage_available_rate: float = 0.0
    max_fallback_rate: float = 1.0
    max_tool_failure_rate: float = 1.0
    max_retry_rate: float = 1.0
    max_timeout_rate: float = 1.0
    max_latency_p95_ms: int = 0
    max_redundant_action_rate: float = 0.0
    max_react_limit_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class AgentRegressionQualityResult:
    passed: bool
    checks: dict[str, bool]
    failures: tuple[str, ...]


def load_quality_thresholds(path: str | Path) -> AgentRegressionQualityThresholds:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Regression quality threshold file must contain an object.")
    return AgentRegressionQualityThresholds(**payload)


def evaluate_regression_quality(
    batch: AgentEvaluationBatchResult,
    thresholds: AgentRegressionQualityThresholds,
) -> AgentRegressionQualityResult:
    trajectory_rate = (
        batch.trajectory_case_count / batch.total_cases if batch.total_cases else 0.0
    )
    values: dict[str, tuple[bool, str]] = {
        "total_cases": (
            batch.total_cases >= thresholds.min_total_cases,
            f"total_cases min={thresholds.min_total_cases} actual={batch.total_cases}",
        ),
        "pass_rate": (
            batch.pass_rate >= thresholds.min_pass_rate,
            f"pass_rate min={thresholds.min_pass_rate} actual={batch.pass_rate}",
        ),
        "intent_accuracy": (
            batch.intent_accuracy >= thresholds.min_intent_accuracy,
            f"intent_accuracy min={thresholds.min_intent_accuracy} actual={batch.intent_accuracy}",
        ),
        "tool_accuracy": (
            batch.tool_accuracy >= thresholds.min_tool_accuracy,
            f"tool_accuracy min={thresholds.min_tool_accuracy} actual={batch.tool_accuracy}",
        ),
        "task_completion_rate": (
            batch.task_completion_rate >= thresholds.min_task_completion_rate,
            "task_completion_rate "
            f"min={thresholds.min_task_completion_rate} actual={batch.task_completion_rate}",
        ),
        "trajectory_case_rate": (
            trajectory_rate >= thresholds.min_trajectory_case_rate,
            "trajectory_case_rate "
            f"min={thresholds.min_trajectory_case_rate} actual={round(trajectory_rate, 4)}",
        ),
        "react_run_rate": (
            batch.react_run_rate >= thresholds.min_react_run_rate,
            f"react_run_rate min={thresholds.min_react_run_rate} actual={batch.react_run_rate}",
        ),
        "grounded_rate": (
            batch.grounded_rate >= thresholds.min_grounded_rate,
            f"grounded_rate min={thresholds.min_grounded_rate} actual={batch.grounded_rate}",
        ),
        "grounding_verification_run_rate": (
            batch.grounding_verification_run_rate
            >= thresholds.min_grounding_verification_run_rate,
            "grounding_verification_run_rate "
            f"min={thresholds.min_grounding_verification_run_rate} "
            f"actual={batch.grounding_verification_run_rate}",
        ),
        "confirmation_guard_rate": (
            batch.confirmation_guard_rate >= thresholds.min_confirmation_guard_rate,
            "confirmation_guard_rate "
            f"min={thresholds.min_confirmation_guard_rate} "
            f"actual={batch.confirmation_guard_rate}",
        ),
        "fallback_accuracy": (
            batch.fallback_accuracy >= thresholds.min_fallback_accuracy,
            f"fallback_accuracy min={thresholds.min_fallback_accuracy} actual={batch.fallback_accuracy}",
        ),
        "evidence_gate_accuracy": (
            batch.evidence_gate_accuracy >= thresholds.min_evidence_gate_accuracy,
            "evidence_gate_accuracy "
            f"min={thresholds.min_evidence_gate_accuracy} actual={batch.evidence_gate_accuracy}",
        ),
        "token_usage_available_rate": (
            batch.token_usage_available_rate
            >= thresholds.min_token_usage_available_rate,
            "token_usage_available_rate "
            f"min={thresholds.min_token_usage_available_rate} "
            f"actual={batch.token_usage_available_rate}",
        ),
        "fallback_rate": (
            batch.fallback_rate <= thresholds.max_fallback_rate,
            f"fallback_rate max={thresholds.max_fallback_rate} actual={batch.fallback_rate}",
        ),
        "tool_failure_rate": (
            batch.tool_failure_rate <= thresholds.max_tool_failure_rate,
            "tool_failure_rate "
            f"max={thresholds.max_tool_failure_rate} actual={batch.tool_failure_rate}",
        ),
        "retry_rate": (
            batch.retry_rate <= thresholds.max_retry_rate,
            f"retry_rate max={thresholds.max_retry_rate} actual={batch.retry_rate}",
        ),
        "timeout_rate": (
            batch.timeout_rate <= thresholds.max_timeout_rate,
            f"timeout_rate max={thresholds.max_timeout_rate} actual={batch.timeout_rate}",
        ),
        "latency_p95_ms": (
            thresholds.max_latency_p95_ms <= 0
            or batch.latency_p95_ms <= thresholds.max_latency_p95_ms,
            f"latency_p95_ms max={thresholds.max_latency_p95_ms} actual={batch.latency_p95_ms}",
        ),
        "redundant_action_rate": (
            batch.redundant_action_rate <= thresholds.max_redundant_action_rate,
            "redundant_action_rate "
            f"max={thresholds.max_redundant_action_rate} actual={batch.redundant_action_rate}",
        ),
        "react_limit_rate": (
            batch.react_limit_rate <= thresholds.max_react_limit_rate,
            f"react_limit_rate max={thresholds.max_react_limit_rate} actual={batch.react_limit_rate}",
        ),
    }
    checks = {name: passed for name, (passed, _message) in values.items()}
    failures = tuple(message for passed, message in values.values() if not passed)
    return AgentRegressionQualityResult(
        passed=all(checks.values()),
        checks=checks,
        failures=failures,
    )


__all__ = [
    "AgentRegressionQualityResult",
    "AgentRegressionQualityThresholds",
    "evaluate_regression_quality",
    "load_quality_thresholds",
]
