from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.errors import AIResponseError
from backend.models.agent_tools import AgentPlan
from backend.services.agent_security_service import AgentSecurityService
from backend.services.agent_tool_registry import AgentToolRegistry


READING = {
    "source_text": "Gaussian processes provide a statistical anchor.",
    "translated_text": "高斯过程提供统计锚点。",
    "source_language": "en",
    "target_language": "zh-CN",
    "resource_url": "file:///paper.pdf",
    "resource_title": "Control paper",
    "section_heading": "3.4 Local refinement",
    "context_before": "Before",
    "context_after": "After",
    "source_kind": "pdf_uia",
}


class FakeTranslationService:
    def translate(self, source_text: str, **kwargs):
        return SimpleNamespace(
            translated_text="deterministic translation",
            provider="google_web",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
        )


class FakeQuickActionService:
    def run(self, **kwargs):
        return SimpleNamespace(
            action=kwargs["action"],
            output_text=f"result:{kwargs['action']}",
            provider="stub-ai",
            model="stub-model",
            request_id=kwargs["request_id"],
        )


class FakeResearchNoteService:
    def save(self, **kwargs):
        note = SimpleNamespace(
            note_id="note-1",
            display_title="Control paper",
            excerpt=kwargs["source_text"],
            updated_at="2026-08-23T00:00:00+00:00",
            conversation_id=kwargs["conversation_id"],
        )
        return SimpleNamespace(note=note, created=True)


def make_registry() -> AgentToolRegistry:
    return AgentToolRegistry(
        translation_service=FakeTranslationService(),
        quick_action_service=FakeQuickActionService(),
        research_note_service=FakeResearchNoteService(),
    )


def test_builtin_tools_expose_typed_args_results_and_policy() -> None:
    registry = make_registry()
    translate = registry.get_definition("translate_selection")
    save = registry.get_definition("save_research_note")

    assert translate is not None
    assert save is not None
    assert translate.args_model.__name__ == "TranslateSelectionArgs"
    assert translate.result_model.__name__ == "TranslationResultData"
    assert translate.allows_safe_retry is True
    assert save.args_model.__name__ == "SaveResearchNoteArgs"
    assert save.result_model.__name__ == "ResearchNoteResultData"
    assert save.allows_safe_retry is False


def test_planner_schema_is_generated_from_tool_owned_models() -> None:
    registry = make_registry()
    translate = registry.get_tool("translate_selection")
    polish = registry.get_tool("polish_selection")
    save = registry.get_tool("save_research_note")

    assert translate is not None
    assert polish is not None
    assert save is not None
    assert set(translate.input_schema) == {"target_language"}
    assert translate.input_schema["target_language"]["maxLength"] == 64
    assert set(polish.input_schema) == {"style"}
    assert polish.input_schema["style"]["maxLength"] == 64
    assert set(save.input_schema) == {"user_note"}
    assert save.input_schema["user_note"]["maxLength"] == 4000


def test_security_uses_tool_schema_instead_of_global_argument_allowlist() -> None:
    registry = make_registry()
    security = AgentSecurityService()
    tools = registry.list_tools()

    valid = security.validate_plan(
        AgentPlan(
            action="tool",
            tool_name="translate_selection",
            arguments={"target_language": "  ja  "},
        ),
        tools=tools,
    )
    assert valid.arguments == {"target_language": "ja"}

    with pytest.raises(AIResponseError, match="outside its authority"):
        security.validate_plan(
            AgentPlan(
                action="tool",
                tool_name="save_research_note",
                arguments={"conversation_id": "planner-controlled"},
            ),
            tools=tools,
        )

    with pytest.raises(AIResponseError, match="exceeds the allowed length"):
        security.validate_plan(
            AgentPlan(
                action="tool",
                tool_name="save_research_note",
                arguments={"user_note": "N" * 4001},
            ),
            tools=tools,
        )


def test_typed_dispatch_preserves_existing_tool_behavior() -> None:
    registry = make_registry()

    translated = registry.execute(
        "translate_selection",
        **{**READING, "target_language": "ja"},
        request_id=7,
    )
    explained = registry.execute(
        "explain_selection",
        **READING,
        request_id=8,
    )
    saved = registry.execute(
        "save_research_note",
        **READING,
        user_note="Keep this.",
        ai_content="Evidence",
        conversation_id="conversation-1",
        request_id=9,
    )

    assert translated.output_text == "deterministic translation"
    assert translated.data
    assert translated.data["target_language"] == "ja"
    assert explained.data == {"action": "reading_explain"}
    assert saved.effect == "write"
    assert saved.data
    assert saved.data["note_id"] == "note-1"


def test_typed_args_and_results_reject_invalid_shapes() -> None:
    registry = make_registry()

    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.execute(
            "polish_selection",
            **READING,
            style="x" * 65,
        )

    definition = registry.get_definition("translate_selection")
    assert definition is not None
    with pytest.raises(ValueError, match="invalid structured result"):
        definition.normalize_result_data({"fallback_level": -1})
