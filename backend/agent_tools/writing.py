from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    TypedAgentToolDefinition,
    typed_tool_definition,
)


class PolishSelectionArgs(AgentToolModel):
    style: str = Field(default="academic", min_length=1, max_length=64)


class WritingResultData(AgentToolModel):
    action: str = Field(min_length=1, max_length=128)


class WritingAgentTool:
    """Agent-facing writing capability over the frozen reading context."""

    def __init__(self, *, quick_action_service: Any) -> None:
        self._quick_action_service = quick_action_service

    def polish_selection(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(PolishSelectionArgs, args)
        result = self._quick_action_service.run(
            action="ai_polish",
            **context.reading_payload(),
            style=typed.style,
            request_id=context.request_id,
        )
        return AgentToolExecutionResult(
            tool_name="polish_selection",
            output_text=result.output_text,
            effect="compute",
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            data={"action": result.action},
        )


def build_writing_tool_definition(tool: WritingAgentTool) -> TypedAgentToolDefinition:
    return typed_tool_definition(
        name="polish_selection",
        title="Polish selection",
        description="Polish the selected text while preserving its language and meaning.",
        category="writing",
        effect="compute",
        requires_reading_context=True,
        requires_confirmation=False,
        args_model=PolishSelectionArgs,
        result_model=WritingResultData,
        executor=tool.polish_selection,
        planner_args_model=PolishSelectionArgs,
        retry_policy="safe",
    )


__all__ = [
    "PolishSelectionArgs",
    "WritingAgentTool",
    "WritingResultData",
    "build_writing_tool_definition",
]
