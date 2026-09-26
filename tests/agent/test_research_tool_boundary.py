from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.research import (
    GetResearchNoteArgs,
    ListResearchNotesArgs,
    ResearchAgentTools,
    SaveResearchNoteArgs,
    UpdateResearchNoteArgs,
    build_research_tool_definitions,
)
from backend.services.agent_tool_registry import AgentToolRegistry


@dataclass(frozen=True)
class StubNote:
    note_id: str = "note-1"
    created_at: str = "2026-08-23T00:00:00+00:00"
    updated_at: str = "2026-08-23T00:01:00+00:00"
    resource_url: str = "file:///paper.pdf"
    resource_title: str = "Control paper"
    section_heading: str = "Methods"
    source_kind: str = "pdf_uia"
    source_text: str = "Gaussian processes model uncertainty."
    translated_text: str = "高斯过程对不确定性进行建模。"
    ai_content: str = "AI evidence"
    ai_action: str = "reading_explain"
    user_note: str = "Initial annotation"
    conversation_id: str = "conversation-1"

    @property
    def display_title(self) -> str:
        return self.resource_title

    @property
    def excerpt(self) -> str:
        return self.source_text


class StubResearchNoteService:
    def __init__(self) -> None:
        self.note = StubNote()
        self.save_calls: list[dict[str, object]] = []
        self.list_calls: list[int] = []
        self.get_calls: list[str] = []
        self.update_calls: list[tuple[str, str]] = []

    def save(self, **kwargs):
        self.save_calls.append(dict(kwargs))
        return SimpleNamespace(note=self.note, created=True)

    def list_recent(self, *, limit: int):
        self.list_calls.append(limit)
        return (self.note,)

    def get(self, note_id: str):
        self.get_calls.append(note_id)
        return self.note if note_id == self.note.note_id else None

    def update_user_note(self, note_id: str, user_note: str):
        self.update_calls.append((note_id, user_note))
        if note_id != self.note.note_id:
            return None
        self.note = replace(self.note, user_note=user_note)
        return self.note


class StubTranslationService:
    def translate(self, source_text: str, **kwargs):
        return SimpleNamespace(
            translated_text=f"translated:{source_text}",
            provider="stub-translation",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            request_id=kwargs["request_id"],
        )


class StubQuickActionService:
    def run(self, **kwargs):
        return SimpleNamespace(
            action=kwargs["action"],
            output_text=f"output:{kwargs['action']}",
            provider="stub-ai",
            model="stub-model",
            request_id=kwargs["request_id"],
        )


def reading_context() -> AgentToolInvocationContext:
    return AgentToolInvocationContext(
        source_text="Gaussian processes model uncertainty.",
        translated_text="高斯过程对不确定性进行建模。",
        source_language="en",
        target_language="zh-CN",
        resource_url="file:///paper.pdf",
        resource_title="Control paper",
        section_heading="Methods",
        source_kind="pdf_uia",
        ai_action="reading_explain",
        request_id=41,
    )


def test_research_agent_tool_owns_save_boundary() -> None:
    service = StubResearchNoteService()
    tools = ResearchAgentTools(research_note_service=service)

    result = tools.save_research_note(
        reading_context(),
        SaveResearchNoteArgs(
            user_note="Keep this evidence.",
            ai_content="Structured evidence",
            conversation_id="conversation-2",
        ),
    )

    assert result.tool_name == "save_research_note"
    assert result.effect == "write"
    assert result.data is not None
    assert result.data["note_id"] == "note-1"
    assert service.save_calls == [
        {
            "source_text": "Gaussian processes model uncertainty.",
            "translated_text": "高斯过程对不确定性进行建模。",
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_url": "file:///paper.pdf",
            "resource_title": "Control paper",
            "section_heading": "Methods",
            "context_before": "",
            "context_after": "",
            "source_kind": "pdf_uia",
            "ai_content": "Structured evidence",
            "ai_action": "reading_explain",
            "user_note": "Keep this evidence.",
            "conversation_id": "conversation-2",
        }
    ]


def test_research_read_and_update_tools_use_existing_service_capabilities() -> None:
    service = StubResearchNoteService()
    tools = ResearchAgentTools(research_note_service=service)
    context = AgentToolInvocationContext(request_id=42)

    listed = tools.list_research_notes(context, ListResearchNotesArgs(limit=3))
    loaded = tools.get_research_note(context, GetResearchNoteArgs(note_id="note-1"))
    updated = tools.update_research_note(
        context,
        UpdateResearchNoteArgs(note_id="note-1", user_note="Revised annotation"),
    )

    assert listed.effect == "read"
    assert listed.data == {
        "notes": [
            {
                "note_id": "note-1",
                "display_title": "Control paper",
                "excerpt": "Gaussian processes model uncertainty.",
                "updated_at": "2026-08-23T00:01:00+00:00",
                "resource_title": "Control paper",
                "section_heading": "Methods",
                "source_kind": "pdf_uia",
                "conversation_id": "conversation-1",
            }
        ],
        "count": 1,
    }
    assert loaded.data is not None and loaded.data["found"] is True
    assert loaded.data["note"]["user_note"] == "Initial annotation"
    assert updated.effect == "write"
    assert updated.data is not None and updated.data["updated"] is True
    assert updated.data["note"]["user_note"] == "Revised annotation"
    assert service.list_calls == [3]
    assert service.get_calls == ["note-1"]
    assert service.update_calls == [("note-1", "Revised annotation")]


def test_research_definitions_encode_read_write_safety_policy() -> None:
    definitions = build_research_tool_definitions(
        ResearchAgentTools(research_note_service=StubResearchNoteService())
    )

    assert [definition.spec.name for definition in definitions] == [
        "save_research_note",
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
        "update_research_note",
    ]
    assert [definition.spec.effect for definition in definitions] == [
        "write",
        "read",
        "read",
        "read",
        "write",
    ]
    assert [definition.spec.requires_reading_context for definition in definitions] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert [definition.spec.requires_confirmation for definition in definitions] == [
        True,
        False,
        False,
        False,
        True,
    ]
    assert [definition.allows_safe_retry for definition in definitions] == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert set(definitions[0].spec.input_schema) == {"user_note"}
    assert set(definitions[1].spec.input_schema) == {"limit"}
    assert set(definitions[2].spec.input_schema) == {"query"}
    assert set(definitions[3].spec.input_schema) == {"note_id"}
    assert set(definitions[4].spec.input_schema) == {"note_id", "user_note"}


def test_registry_exposes_research_memory_without_exposing_delete() -> None:
    research = StubResearchNoteService()
    registry = AgentToolRegistry(
        translation_service=StubTranslationService(),
        quick_action_service=StubQuickActionService(),
        research_note_service=research,
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
    assert registry.get_tool("delete_research_note") is None

    listed = registry.execute("list_research_notes", limit=2, request_id=43)
    loaded = registry.execute("get_research_note", note_id="note-1", request_id=44)
    updated = registry.execute(
        "update_research_note",
        note_id="note-1",
        user_note="Registry update",
        request_id=45,
    )

    assert listed.data is not None and listed.data["count"] == 1
    assert loaded.data is not None and loaded.data["found"] is True
    assert updated.data is not None and updated.data["updated"] is True
    assert registry.allows_safe_retry("list_research_notes") is True
    assert registry.allows_safe_retry("search_research_notes") is True
    assert registry.allows_safe_retry("get_research_note") is True
    assert registry.allows_safe_retry("update_research_note") is False
