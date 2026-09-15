from __future__ import annotations

from typing import Any

from backend.agent_tools.base import TypedAgentToolDefinition
from backend.agent_tools.reading import (
    InspectReadingContextResultData,
    QuickActionResultData,
    ReadingAgentTools,
    build_reading_tool_definitions,
)
from backend.agent_tools.research import (
    ResearchAgentTools,
    ResearchNoteResultData,
    SaveResearchNoteArgs,
    SaveResearchNotePlannerArgs,
    build_research_tool_definitions,
)
from backend.agent_tools.translation import (
    TranslateSelectionArgs,
    TranslationResultData,
)
from backend.agent_tools.writing import (
    PolishSelectionArgs,
    WritingAgentTool,
    WritingResultData,
    build_writing_tool_definition,
)


class BuiltinAgentToolExecutors:
    """Compatibility container for pre-Stage-10.4 tool-builder callers."""

    def __init__(
        self,
        *,
        quick_action_service: Any,
        research_note_service: Any | None = None,
    ) -> None:
        self._quick_action_service = quick_action_service
        self._research_note_service = research_note_service


def build_builtin_tool_definitions(
    executors: BuiltinAgentToolExecutors,
    *,
    translation_definition: TypedAgentToolDefinition | None = None,
) -> tuple[TypedAgentToolDefinition, ...]:
    """Reproduce the historical seven-tool catalog for legacy callers.

    Production ``AgentToolRegistry`` receives all current reading capabilities.
    This compatibility helper intentionally keeps the pre-academic-reading
    surface stable so older integrations do not silently gain new tools.
    """

    writing_definition = build_writing_tool_definition(
        WritingAgentTool(quick_action_service=executors._quick_action_service)
    )
    if translation_definition is None:
        return (writing_definition,)

    reading_definitions = build_reading_tool_definitions(
        ReadingAgentTools(quick_action_service=executors._quick_action_service)
    )
    reading_by_name = {
        definition.spec.name: definition for definition in reading_definitions
    }
    research_definitions = build_research_tool_definitions(
        ResearchAgentTools(research_note_service=executors._research_note_service)
    )
    return (
        reading_by_name["inspect_reading_context"],
        translation_definition,
        reading_by_name["explain_selection"],
        reading_by_name["summarize_selection"],
        reading_by_name["analyze_section_role"],
        writing_definition,
        research_definitions[0],
    )


__all__ = [
    "BuiltinAgentToolExecutors",
    "InspectReadingContextResultData",
    "PolishSelectionArgs",
    "QuickActionResultData",
    "ResearchNoteResultData",
    "SaveResearchNoteArgs",
    "SaveResearchNotePlannerArgs",
    "TranslateSelectionArgs",
    "TranslationResultData",
    "WritingResultData",
    "build_builtin_tool_definitions",
]
