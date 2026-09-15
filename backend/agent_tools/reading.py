from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    EmptyToolArgs,
    TypedAgentToolDefinition,
    typed_tool_definition,
)


class InspectReadingContextResultData(AgentToolModel):
    source_text: str = ""
    translated_text: str = ""
    source_language: str = "auto"
    target_language: str = "zh-CN"
    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    context_before: str = ""
    context_after: str = ""
    source_kind: str = "desktop"


class QuickActionResultData(AgentToolModel):
    action: str


class ReadingAgentTools:
    """Agent-facing reading capabilities over the frozen invocation context."""

    def __init__(self, *, quick_action_service: Any) -> None:
        self._quick_action_service = quick_action_service

    def inspect_reading_context(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return AgentToolExecutionResult(
            tool_name="inspect_reading_context",
            output_text=context.source_text,
            effect="read",
            request_id=context.request_id,
            data=context.reading_payload(),
        )

    def _run_quick_action(
        self,
        *,
        tool_name: str,
        action: str,
        context: AgentToolInvocationContext,
    ) -> AgentToolExecutionResult:
        result = self._quick_action_service.run(
            action=action,
            **context.reading_payload(),
            style=context.style,
            request_id=context.request_id,
        )
        return AgentToolExecutionResult(
            tool_name=tool_name,
            output_text=result.output_text,
            effect="compute",
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            data={"action": result.action},
        )

    def explain_selection(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(tool_name="explain_selection", action="reading_explain", context=context)

    def summarize_selection(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(tool_name="summarize_selection", action="reading_summarize", context=context)

    def analyze_section_role(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(tool_name="analyze_section_role", action="reading_section_role", context=context)

    def define_terms(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(tool_name="define_terms", action="reading_define_terms", context=context)

    def analyze_equation(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(tool_name="analyze_equation", action="reading_analyze_equation", context=context)

    def summarize_current_section(self, context: AgentToolInvocationContext, args: BaseModel) -> AgentToolExecutionResult:
        cast(EmptyToolArgs, args)
        return self._run_quick_action(
            tool_name="summarize_current_section",
            action="reading_section_summarize",
            context=context,
        )


def _reading_compute_definition(
    *,
    name: str,
    title: str,
    description: str,
    executor,
) -> TypedAgentToolDefinition:
    return typed_tool_definition(
        name=name,
        title=title,
        description=description,
        category="reading",
        effect="compute",
        requires_reading_context=True,
        requires_confirmation=False,
        args_model=EmptyToolArgs,
        result_model=QuickActionResultData,
        executor=executor,
        retry_policy="safe",
    )


def build_reading_tool_definitions(
    tools: ReadingAgentTools,
) -> tuple[TypedAgentToolDefinition, ...]:
    return (
        typed_tool_definition(
            name="inspect_reading_context",
            title="Inspect reading context",
            description="Return the frozen reading selection and nearby source metadata available to the Agent.",
            category="context",
            effect="read",
            requires_reading_context=True,
            requires_confirmation=False,
            args_model=EmptyToolArgs,
            result_model=InspectReadingContextResultData,
            executor=tools.inspect_reading_context,
            retry_policy="safe",
        ),
        _reading_compute_definition(
            name="explain_selection",
            title="Explain selection",
            description="Explain the selected text using only the frozen reading context available to the Agent.",
            executor=tools.explain_selection,
        ),
        _reading_compute_definition(
            name="summarize_selection",
            title="Summarize selection",
            description="Summarize the selected text using only the frozen reading context available to the Agent.",
            executor=tools.summarize_selection,
        ),
        _reading_compute_definition(
            name="analyze_section_role",
            title="Analyze section role",
            description="Analyze how the selected passage functions inside its current section or document context.",
            executor=tools.analyze_section_role,
        ),
        _reading_compute_definition(
            name="define_terms",
            title="Define academic terms",
            description="Identify and explain important academic terms in the current reading context without replacing document-specific meaning with generic definitions.",
            executor=tools.define_terms,
        ),
        _reading_compute_definition(
            name="analyze_equation",
            title="Analyze equation",
            description="Explain variables, relationships, supported assumptions, and the role of an equation present in the current academic reading context.",
            executor=tools.analyze_equation,
        ),
        _reading_compute_definition(
            name="summarize_current_section",
            title="Summarize current section",
            description="Summarize the current academic section from its heading and available bounded reading context, explicitly noting incomplete context.",
            executor=tools.summarize_current_section,
        ),
    )


__all__ = [
    "InspectReadingContextResultData",
    "QuickActionResultData",
    "ReadingAgentTools",
    "build_reading_tool_definitions",
]
