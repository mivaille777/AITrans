from __future__ import annotations

from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext, EmptyToolArgs
from backend.agent_tools.reading import ReadingAgentTools, build_reading_tool_definitions
from backend.services.agent_tool_registry import AgentToolRegistry


class StubQuickActionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            action=kwargs["action"],
            output_text=f"output:{kwargs['action']}",
            provider="stub-reading",
            model="stub-model",
            request_id=kwargs["request_id"],
        )


class StubTranslationService:
    def translate(self, source_text: str, **kwargs):
        return SimpleNamespace(
            translated_text=f"translated:{source_text}",
            provider="stub-translation",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
        )


class StubResearchNoteService:
    def save(self, **_kwargs):
        raise AssertionError("research write should not run in Reading Tool tests")


def reading_context() -> AgentToolInvocationContext:
    return AgentToolInvocationContext(
        source_text="Gaussian processes model uncertainty.",
        translated_text="高斯过程对不确定性进行建模。",
        source_language="en",
        target_language="zh-CN",
        resource_url="file:///paper.pdf",
        resource_title="Control paper",
        section_heading="Methods",
        context_before="Previous paragraph",
        context_after="Next paragraph",
        source_kind="pdf_uia",
        style="academic",
        request_id=12,
    )


def test_inspect_reading_context_is_a_pure_read_tool() -> None:
    quick_action = StubQuickActionService()
    tools = ReadingAgentTools(quick_action_service=quick_action)

    result = tools.inspect_reading_context(reading_context(), EmptyToolArgs())

    assert result.tool_name == "inspect_reading_context"
    assert result.effect == "read"
    assert result.output_text == "Gaussian processes model uncertainty."
    assert result.data is not None
    assert result.data["resource_title"] == "Control paper"
    assert result.data["section_heading"] == "Methods"
    assert quick_action.calls == []


def test_reading_compute_tools_share_the_frozen_context_boundary() -> None:
    quick_action = StubQuickActionService()
    tools = ReadingAgentTools(quick_action_service=quick_action)
    context = reading_context()

    explained = tools.explain_selection(context, EmptyToolArgs())
    summarized = tools.summarize_selection(context, EmptyToolArgs())
    analyzed = tools.analyze_section_role(context, EmptyToolArgs())

    assert [item.tool_name for item in (explained, summarized, analyzed)] == [
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
    ]
    assert [call["action"] for call in quick_action.calls] == [
        "reading_explain",
        "reading_summarize",
        "reading_section_role",
    ]
    assert all(call["source_text"] == context.source_text for call in quick_action.calls)
    assert all(call["resource_title"] == context.resource_title for call in quick_action.calls)
    assert all(call["section_heading"] == context.section_heading for call in quick_action.calls)
    assert all(call["request_id"] == 12 for call in quick_action.calls)
    assert explained.provider == "stub-reading"
    assert summarized.model == "stub-model"
    assert analyzed.data == {"action": "reading_section_role"}


def test_reading_definitions_expose_stable_public_contracts() -> None:
    definitions = build_reading_tool_definitions(
        ReadingAgentTools(quick_action_service=StubQuickActionService())
    )

    assert [definition.spec.name for definition in definitions] == [
        "inspect_reading_context",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "define_terms",
        "analyze_equation",
        "summarize_current_section",
    ]
    assert [definition.spec.effect for definition in definitions] == [
        "read",
        "compute",
        "compute",
        "compute",
        "compute",
        "compute",
        "compute",
    ]
    assert all(definition.spec.requires_reading_context for definition in definitions)
    assert all(definition.spec.requires_confirmation is False for definition in definitions)
    assert all(definition.allows_safe_retry for definition in definitions)


def test_registry_preserves_existing_tool_catalog_order_and_dispatch() -> None:
    quick_action = StubQuickActionService()
    registry = AgentToolRegistry(
        translation_service=StubTranslationService(),
        quick_action_service=quick_action,
        research_note_service=StubResearchNoteService(),
    )

    names = [tool.name for tool in registry.list_tools()]
    assert names[:7] == [
        "inspect_reading_context",
        "translate_selection",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "polish_selection",
        "save_research_note",
    ]
    assert names[7:11] == [
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
        "update_research_note",
    ]
    assert names[11:14] == [
        "define_terms",
        "analyze_equation",
        "summarize_current_section",
    ]

    result = registry.execute(
        "summarize_selection",
        source_text="Evidence",
        translated_text="证据",
        source_language="en",
        target_language="zh-CN",
        resource_title="Paper",
        section_heading="Results",
        source_kind="pdf_uia",
        request_id=19,
    )

    assert result.tool_name == "summarize_selection"
    assert result.data == {"action": "reading_summarize"}
    assert quick_action.calls[-1]["request_id"] == 19
