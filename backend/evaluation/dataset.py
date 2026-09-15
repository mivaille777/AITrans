from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from backend.evaluation.agent_evaluator import AgentEvaluationExpectation


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    return max(0, int(value))


def load_evaluation_dataset(path: str | Path) -> tuple[AgentEvaluationExpectation, ...]:
    dataset_path = Path(path)
    cases: list[AgentEvaluationExpectation] = []
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Evaluation case line {line_number} must be an object.")
        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            raise ValueError(f"Evaluation case line {line_number} is missing case_id.")
        raw_sequence = payload.get("expected_tool_sequence", [])
        if raw_sequence is None:
            raw_sequence = []
        if not isinstance(raw_sequence, list):
            raise ValueError(
                f"Evaluation case line {line_number} expected_tool_sequence must be a list."
            )
        cases.append(
            AgentEvaluationExpectation(
                case_id=case_id,
                expected_intent=str(payload.get("expected_intent", "") or ""),
                expected_tool_name=str(payload.get("expected_tool_name", "") or ""),
                expected_tool_sequence=tuple(
                    str(item).strip() for item in raw_sequence if str(item).strip()
                ),
                expected_status=str(payload.get("expected_status", "completed") or "completed"),
                expected_fallback_reason=str(
                    payload.get("expected_fallback_reason", "") or ""
                ),
                expected_final_evidence_gate_action=str(
                    payload.get("expected_final_evidence_gate_action", "") or ""
                ),
                expected_grounding_verification_pass=_optional_bool(
                    payload.get("expected_grounding_verification_pass")
                ),
                max_total_duration_ms=max(0, int(payload.get("max_total_duration_ms", 0) or 0)),
                max_retry_count=max(0, int(payload.get("max_retry_count", 0) or 0)),
                require_zero_failures=bool(payload.get("require_zero_failures", True)),
                expect_react=_optional_bool(payload.get("expect_react")),
                max_react_iterations=max(0, int(payload.get("max_react_iterations", 0) or 0)),
                max_tool_calls=max(0, int(payload.get("max_tool_calls", 0) or 0)),
                max_redundant_actions=_optional_non_negative_int(
                    payload.get("max_redundant_actions")
                ),
                require_no_react_limit=bool(payload.get("require_no_react_limit", False)),
                require_grounded_response=bool(
                    payload.get("require_grounded_response", False)
                ),
                require_grounding_verification_pass=bool(
                    payload.get("require_grounding_verification_pass", False)
                ),
                require_confirmation_guard=bool(
                    payload.get("require_confirmation_guard", False)
                ),
            )
        )
    return tuple(cases)


def write_evaluation_dataset(
    path: str | Path,
    cases: Iterable[AgentEvaluationExpectation],
) -> None:
    dataset_path = Path(path)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "case_id": case.case_id,
                "expected_intent": case.expected_intent,
                "expected_tool_name": case.expected_tool_name,
                "expected_tool_sequence": list(case.expected_tool_sequence),
                "expected_status": case.expected_status,
                "expected_fallback_reason": case.expected_fallback_reason,
                "expected_final_evidence_gate_action": case.expected_final_evidence_gate_action,
                "expected_grounding_verification_pass": case.expected_grounding_verification_pass,
                "max_total_duration_ms": case.max_total_duration_ms,
                "max_retry_count": case.max_retry_count,
                "require_zero_failures": case.require_zero_failures,
                "expect_react": case.expect_react,
                "max_react_iterations": case.max_react_iterations,
                "max_tool_calls": case.max_tool_calls,
                "max_redundant_actions": case.max_redundant_actions,
                "require_no_react_limit": case.require_no_react_limit,
                "require_grounded_response": case.require_grounded_response,
                "require_grounding_verification_pass": case.require_grounding_verification_pass,
                "require_confirmation_guard": case.require_confirmation_guard,
            },
            ensure_ascii=False,
        )
        for case in cases
    ]
    dataset_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


__all__ = ["load_evaluation_dataset", "write_evaluation_dataset"]
