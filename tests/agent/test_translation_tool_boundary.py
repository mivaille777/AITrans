from __future__ import annotations

from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.builtin import BuiltinAgentToolExecutors, build_builtin_tool_definitions
from backend.agent_tools.translation import (
    TranslateSelectionArgs,
    TranslationAgentTool,
    build_translation_tool_definition,
)
from backend.services.agent_tool_registry import AgentToolRegistry


class StubCascade:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def translate(self, source_text: str, **kwargs):
        self.calls.append({"source_text": source_text, **kwargs})
        return SimpleNamespace(
            translated_text="高斯过程",
            provider="ai",
            model="deepseek-v4-flash",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
            fallback_level=2,
            notice="fallback to AI",
            attempts=(
                SimpleNamespace(provider="youdao_web", status="unavailable"),
                SimpleNamespace(provider="google_web", status="unavailable"),
                SimpleNamespace(provider="ai", status="success"),
            ),
        )


class StubQuickAction:
    def run(self, **_kwargs):
        raise AssertionError("quick action should not run")


class StubResearch:
    def save(self, **_kwargs):
        raise AssertionError("research write should not run")


def test_translation_agent_tool_owns_translation_service_boundary() -> None:
    cascade = StubCascade()
    tool = TranslationAgentTool(
        translation_service=None,
        translation_fallback_service=cascade,
    )
    context = AgentToolInvocationContext(
        source_text="Gaussian process",
        source_language="en",
        target_language="zh-CN",
        request_id=31,
    )

    result = tool.execute(context, TranslateSelectionArgs(target_language="zh-CN"))

    assert result.tool_name == "translate_selection"
    assert result.output_text == "高斯过程"
    assert result.provider == "ai"
    assert result.model == "deepseek-v4-flash"
    assert result.request_id == 31
    assert result.data is not None
    assert result.data["fallback_level"] == 2
    assert result.data["attempts"][-1] == {"provider": "ai", "status": "success"}
    assert cascade.calls == [
        {
            "source_text": "Gaussian process",
            "source_language": "en",
            "target_language": "zh-CN",
            "request_id": 31,
        }
    ]


def test_translation_definition_is_injected_as_normal_typed_tool() -> None:
    translation = build_translation_tool_definition(
        TranslationAgentTool(
            translation_service=None,
            translation_fallback_service=StubCascade(),
        )
    )
    executors = BuiltinAgentToolExecutors(
        quick_action_service=StubQuickAction(),
        research_note_service=StubResearch(),
    )

    definitions = build_builtin_tool_definitions(
        executors,
        translation_definition=translation,
    )

    assert [definition.spec.name for definition in definitions[:3]] == [
        "inspect_reading_context",
        "translate_selection",
        "explain_selection",
    ]
    assert definitions[1] is translation
    assert definitions[1].spec.effect == "compute"
    assert definitions[1].allows_safe_retry


def test_registry_preserves_translation_external_contract() -> None:
    registry = AgentToolRegistry(
        translation_fallback_service=StubCascade(),
        quick_action_service=StubQuickAction(),
        research_note_service=StubResearch(),
    )

    spec = registry.get_tool("translate_selection")
    assert spec is not None
    assert spec.category == "translation"
    assert spec.requires_reading_context
    assert not spec.requires_confirmation
    assert "target_language" in spec.input_schema

    result = registry.execute(
        "translate_selection",
        source_text="Gaussian process",
        source_language="en",
        target_language="zh-CN",
        request_id=32,
    )
    assert result.output_text == "高斯过程"
