from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.dependencies import get_agent_tool_registry
from backend.main import create_app
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
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def translate(self, source_text: str, **kwargs):
        self.calls.append({"source_text": source_text, **kwargs})
        return SimpleNamespace(
            translated_text="deterministic translation",
            provider="google_web",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
        )


class FakeQuickActionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            action=kwargs["action"],
            output_text=f"result:{kwargs['action']}",
            provider="stub-ai",
            model="stub-model",
            request_id=kwargs["request_id"],
        )


class FakeResearchNoteService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def save(self, **kwargs):
        self.calls.append(kwargs)
        note = SimpleNamespace(
            note_id="note-1",
            display_title="Control paper",
            excerpt="Gaussian processes provide a statistical anchor.",
            updated_at="2026-08-22T00:00:00+00:00",
            conversation_id=kwargs["conversation_id"],
        )
        return SimpleNamespace(note=note, created=True)


def make_registry():
    translation = FakeTranslationService()
    quick = FakeQuickActionService()
    research = FakeResearchNoteService()
    registry = AgentToolRegistry(
        translation_service=translation,
        quick_action_service=quick,
        research_note_service=research,
        jit_search_read_enabled=True,
    )
    return registry, translation, quick, research


def test_agent_tool_catalog_declares_side_effect_boundaries() -> None:
    registry, *_ = make_registry()
    tools = {tool.name: tool for tool in registry.list_tools()}

    assert set(tools) == {
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
    }
    assert tools["translate_selection"].effect == "compute"
    assert tools["translate_selection"].requires_confirmation is False
    assert tools["save_research_note"].effect == "write"
    assert tools["save_research_note"].requires_confirmation is True
    assert tools["list_research_notes"].effect == "read"
    assert tools["list_research_notes"].requires_confirmation is False
    assert tools["search_research_notes"].effect == "read"
    assert tools["search_research_notes"].requires_confirmation is False
    assert tools["get_research_note"].effect == "read"
    assert tools["get_research_note"].requires_confirmation is False
    assert tools["update_research_note"].effect == "write"
    assert tools["update_research_note"].requires_confirmation is True
    assert tools["define_terms"].effect == "compute"
    assert tools["analyze_equation"].effect == "compute"
    assert tools["summarize_current_section"].effect == "compute"
    assert tools["search_knowledge_base"].effect == "read"
    assert tools["search_knowledge_base"].requires_confirmation is False
    assert tools["save_knowledge_card"].effect == "write"
    assert tools["save_knowledge_card"].requires_confirmation is True
    assert "delete_research_note" not in tools


def test_agent_tool_registry_reuses_existing_translation_and_quick_actions() -> None:
    registry, translation, quick, _ = make_registry()

    translated = registry.execute("translate_selection", **READING, request_id=7)
    explained = registry.execute("explain_selection", **READING, request_id=8)

    assert translated.output_text == "deterministic translation"
    assert translated.provider == "google_web"
    assert translation.calls[0]["source_text"] == READING["source_text"]
    assert explained.output_text == "result:reading_explain"
    assert quick.calls[0]["action"] == "reading_explain"
    assert quick.calls[0]["resource_title"] == "Control paper"


def test_agent_tool_registry_persists_research_note_only_through_write_tool() -> None:
    registry, _, _, research = make_registry()

    result = registry.execute(
        "save_research_note",
        **READING,
        ai_content="Agent evidence",
        ai_action="reading_explain",
        user_note="Keep this argument.",
        conversation_id="conversation-1",
        request_id=9,
    )

    assert result.effect == "write"
    assert result.data and result.data["note_id"] == "note-1"
    assert result.data["conversation_id"] == "conversation-1"
    assert research.calls[0]["ai_content"] == "Agent evidence"
    assert research.calls[0]["user_note"] == "Keep this argument."


def test_inspect_reading_context_is_deterministic_and_service_free() -> None:
    registry, translation, quick, research = make_registry()

    result = registry.execute("inspect_reading_context", **READING)

    assert result.effect == "read"
    assert result.output_text == READING["source_text"]
    assert result.data and result.data["section_heading"] == "3.4 Local refinement"
    assert translation.calls == []
    assert quick.calls == []
    assert research.calls == []


def test_agent_tool_http_contract_exposes_catalog_and_execution() -> None:
    registry, *_ = make_registry()
    app = create_app()
    app.dependency_overrides[get_agent_tool_registry] = lambda: registry
    client = TestClient(app)

    catalog = client.get("/api/agent/tools")
    assert catalog.status_code == 200
    save_tool = next(
        item for item in catalog.json()["tools"] if item["name"] == "save_research_note"
    )
    assert save_tool["effect"] == "write"
    assert save_tool["requires_confirmation"] is True

    knowledge_save_tool = next(
        item for item in catalog.json()["tools"] if item["name"] == "save_knowledge_card"
    )
    assert knowledge_save_tool["effect"] == "write"
    assert knowledge_save_tool["requires_confirmation"] is True

    executed = client.post(
        "/api/agent/tools/inspect_reading_context/execute",
        json=READING,
    )
    assert executed.status_code == 200
    assert executed.json()["tool_name"] == "inspect_reading_context"
    assert executed.json()["data"]["resource_title"] == "Control paper"

    unknown = client.post("/api/agent/tools/not_registered/execute", json=READING)
    assert unknown.status_code == 404
