from __future__ import annotations

from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.writing import (
    PolishSelectionArgs,
    WritingAgentTool,
    WritingResultData,
    build_writing_tool_definition,
)
from backend.services.agent_tool_registry import AgentToolRegistry


class StubQuickActionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            action=kwargs["action"],
            output_text="Polished scientific passage.",
            provider="stub-writing",
            model="stub-model",
            request_id=kwargs["request_id"],
        )


class StubTranslationService:
    def translate(self, source_text: str, **kwargs):
        return SimpleNamespace(
            translated_text=source_text,
            provider="stub-translation",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
        )


class StubResearchNoteService:
    pass


def writing_context() -> AgentToolInvocationContext:
    return AgentToolInvocationContext(
        source_text="Gaussian processes provide uncertainty estimates.",
        translated_text="高斯过程提供不确定性估计。",
        source_language="en",
        target_language="zh-CN",
        resource_url="file:///paper.pdf",
        resource_title="Control paper",
        section_heading="Methods",
        context_before="Previous paragraph",
        context_after="Next paragraph",
        source_kind="pdf_uia",
        style="academic",
        request_id=51,
    )


def test_writing_tool_owns_polish_service_boundary() -> None:
    quick_action = StubQuickActionService()
    tool = WritingAgentTool(quick_action_service=quick_action)

    result = tool.polish_selection(
        writing_context(),
        PolishSelectionArgs(style="concise"),
    )

    assert result.tool_name == "polish_selection"
    assert result.effect == "compute"
    assert result.output_text == "Polished scientific passage."
    assert result.provider == "stub-writing"
    assert result.model == "stub-model"
    assert result.request_id == 51
    assert result.data == {"action": "ai_polish"}
    assert quick_action.calls == [
        {
            "action": "ai_polish",
            "source_text": "Gaussian processes provide uncertainty estimates.",
            "translated_text": "高斯过程提供不确定性估计。",
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_url": "file:///paper.pdf",
            "resource_title": "Control paper",
            "section_heading": "Methods",
            "context_before": "Previous paragraph",
            "context_after": "Next paragraph",
            "source_kind": "pdf_uia",
            "style": "concise",
            "request_id": 51,
        }
    ]


def test_writing_definition_exposes_stable_public_contract() -> None:
    definition = build_writing_tool_definition(
        WritingAgentTool(quick_action_service=StubQuickActionService())
    )

    assert definition.spec.name == "polish_selection"
    assert definition.spec.category == "writing"
    assert definition.spec.effect == "compute"
    assert definition.spec.requires_reading_context is True
    assert definition.spec.requires_confirmation is False
    assert set(definition.spec.input_schema) == {"style"}
    assert definition.spec.input_schema["style"]["maxLength"] == 64
    assert definition.args_model is PolishSelectionArgs
    assert definition.result_model is WritingResultData
    assert definition.allows_safe_retry is True


def test_registry_uses_dedicated_writing_owner_and_preserves_catalog_order() -> None:
    quick_action = StubQuickActionService()
    registry = AgentToolRegistry(
        translation_service=StubTranslationService(),
        quick_action_service=quick_action,
        research_note_service=StubResearchNoteService(),
        jit_search_read_enabled=True,
    )

    assert [tool.name for tool in registry.list_tools()] == [
        "inspect_reading_context",
        "translate_selection",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "polish_selection",
        "save_research_note",
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
        "update_research_note",
        "define_terms",
        "analyze_equation",
            "summarize_current_section",
            "search_knowledge_base",
            "read_knowledge_chunk",
            "read_knowledge_section",
            "save_knowledge_card",
    ]

    definition = registry.get_definition("polish_selection")
    assert definition is not None
    assert isinstance(getattr(definition.executor, "__self__", None), WritingAgentTool)

    result = registry.execute(
        "polish_selection",
        source_text="Evidence",
        source_language="en",
        target_language="zh-CN",
        style="academic",
        request_id=52,
    )

    assert result.data == {"action": "ai_polish"}
    assert quick_action.calls[-1]["request_id"] == 52
