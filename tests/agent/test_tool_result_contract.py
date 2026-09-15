from __future__ import annotations

import pytest

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    EmptyToolArgs,
    TypedAgentToolDefinition,
    typed_tool_definition,
)


class ProbeResultData(AgentToolModel):
    evidence: str


def _executor(
    _context: AgentToolInvocationContext,
    _args,
) -> AgentToolExecutionResult:
    return AgentToolExecutionResult(
        tool_name="probe_tool",
        output_text="probe",
        effect="read",
        request_id=1,
        data={"evidence": "grounded"},
    )


def probe_definition() -> TypedAgentToolDefinition:
    return typed_tool_definition(
        name="probe_tool",
        title="Probe",
        description="Probe the typed result contract.",
        category="test",
        effect="read",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=EmptyToolArgs,
        result_model=ProbeResultData,
        executor=_executor,
        retry_policy="safe",
    )


def test_result_normalization_preserves_external_envelope_and_types_data() -> None:
    definition = probe_definition()

    normalized = definition.normalize_execution_result(
        AgentToolExecutionResult(
            tool_name="probe_tool",
            output_text="Observation",
            effect="read",
            provider="stub",
            model="model-1",
            request_id=7,
            data={"evidence": "  grounded evidence  "},
        )
    )

    assert normalized == AgentToolExecutionResult(
        tool_name="probe_tool",
        output_text="Observation",
        effect="read",
        provider="stub",
        model="model-1",
        request_id=7,
        data={"evidence": "grounded evidence"},
    )


def test_result_normalization_rejects_mismatched_tool_identity() -> None:
    definition = probe_definition()

    with pytest.raises(ValueError, match="mismatched result"):
        definition.normalize_execution_result(
            AgentToolExecutionResult(
                tool_name="other_tool",
                output_text="Observation",
                effect="read",
                data={"evidence": "grounded"},
            )
        )


def test_result_normalization_rejects_mismatched_effect() -> None:
    definition = probe_definition()

    with pytest.raises(ValueError, match="returned effect"):
        definition.normalize_execution_result(
            AgentToolExecutionResult(
                tool_name="probe_tool",
                output_text="Observation",
                effect="compute",
                data={"evidence": "grounded"},
            )
        )


def test_result_normalization_rejects_invalid_structured_data() -> None:
    definition = probe_definition()

    with pytest.raises(ValueError, match="invalid structured result"):
        definition.normalize_execution_result(
            AgentToolExecutionResult(
                tool_name="probe_tool",
                output_text="Observation",
                effect="read",
                data={},
            )
        )


def test_result_normalization_rejects_invalid_request_id() -> None:
    definition = probe_definition()

    with pytest.raises(ValueError, match="invalid request_id"):
        definition.normalize_execution_result(
            AgentToolExecutionResult(
                tool_name="probe_tool",
                output_text="Observation",
                effect="read",
                request_id=-1,
                data={"evidence": "grounded"},
            )
        )
