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


class TranslateSelectionArgs(AgentToolModel):
    target_language: str = Field(default="zh-CN", min_length=1, max_length=64)


class TranslationAttemptData(AgentToolModel):
    provider: str
    status: str


class TranslationResultData(AgentToolModel):
    source_language: str = "auto"
    target_language: str = "zh-CN"
    fallback_level: int = Field(default=0, ge=0)
    notice: str = ""
    attempts: list[TranslationAttemptData] = Field(default_factory=list)


class TranslationAgentTool:
    """Agent-facing translation capability.

    Product Agent orchestration only knows the typed tool contract. This class
    owns the boundary to the existing translation services so translation is no
    longer a special case inside the generic built-in executor collection.
    """

    def __init__(
        self,
        *,
        translation_service: Any | None,
        translation_fallback_service: Any | None,
    ) -> None:
        self._translation_service = translation_service
        self._translation_fallback_service = translation_fallback_service

    def execute(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(TranslateSelectionArgs, args)
        target_language = typed.target_language or context.target_language

        if self._translation_fallback_service is not None:
            result = self._translation_fallback_service.translate(
                context.source_text,
                source_language=context.source_language,
                target_language=target_language,
                request_id=context.request_id,
            )
            return AgentToolExecutionResult(
                tool_name="translate_selection",
                output_text=result.translated_text,
                effect="compute",
                provider=result.provider,
                model=result.model,
                request_id=result.request_id,
                data={
                    "source_language": result.source_language,
                    "target_language": result.target_language,
                    "fallback_level": result.fallback_level,
                    "notice": result.notice,
                    "attempts": [
                        {"provider": item.provider, "status": item.status}
                        for item in result.attempts
                    ],
                },
            )

        if self._translation_service is None:
            raise RuntimeError("Agent translation service is unavailable.")

        result = self._translation_service.translate(
            context.source_text,
            source_language=context.source_language,
            target_language=target_language,
            request_id=context.request_id,
        )
        return AgentToolExecutionResult(
            tool_name="translate_selection",
            output_text=result.translated_text,
            effect="compute",
            provider=result.provider,
            request_id=result.request_id,
            data={
                "source_language": result.source_language,
                "target_language": result.target_language,
                "fallback_level": 0,
                "notice": "",
                "attempts": [],
            },
        )


def build_translation_tool_definition(
    executor: TranslationAgentTool,
) -> TypedAgentToolDefinition:
    """Build the stable planner/runtime contract for Agent translation."""

    return typed_tool_definition(
        name="translate_selection",
        title="Translate selection",
        description=(
            "Translate the current selected text through the reusable translation "
            "tool capability using the deterministic Youdao, Google, then AI cascade."
        ),
        category="translation",
        effect="compute",
        requires_reading_context=True,
        requires_confirmation=False,
        args_model=TranslateSelectionArgs,
        result_model=TranslationResultData,
        executor=executor.execute,
        planner_args_model=TranslateSelectionArgs,
        retry_policy="safe",
    )


__all__ = [
    "TranslateSelectionArgs",
    "TranslationAgentTool",
    "TranslationAttemptData",
    "TranslationResultData",
    "build_translation_tool_definition",
]
