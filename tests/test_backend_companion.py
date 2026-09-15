from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_companion_chat_service,
    get_companion_handoff_service,
    get_research_note_service,
)
from backend.main import create_app
from backend.services.companion_handoff_service import CompanionHandoffService


def _context_payload() -> dict[str, object]:
    return {
        "source_text": "The LLM performs local refinement around the GP anchor.",
        "translated_text": "LLM 围绕 GP 锚点执行局部细化。",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "https://example.org/paper",
        "resource_title": "A Research Paper",
        "section_heading": "3. Methodology",
        "context_before": "The GP identifies a statistically promising region.",
        "context_after": "The candidate is validated deterministically.",
        "source_kind": "browser_selection",
    }


def test_companion_handoff_does_not_allow_stale_dismissal_to_clear_new_context() -> None:
    service = CompanionHandoffService()
    first = service.create(**_context_payload())
    second_payload = _context_payload()
    second_payload["source_text"] = "A newer selection."
    second = service.create(**second_payload)

    state = service.clear(handoff_id=first.handoff_id)

    assert state is not None
    assert state.handoff_id == second.handoff_id
    assert service.snapshot() == second


def test_companion_handoff_api_round_trips_frozen_reading_context() -> None:
    app = create_app()
    service = CompanionHandoffService()
    app.dependency_overrides[get_companion_handoff_service] = lambda: service

    payload = _context_payload()
    payload["conversation_id"] = "conversation-overlay-7"
    payload["ai_content"] = "Existing explanation"
    payload["ai_action"] = "reading_explain"

    with TestClient(app) as client:
        created = client.post("/api/companion/handoff", json=payload)
        current = client.get("/api/companion/handoff")
        dismissed = client.post(
            "/api/companion/handoff/dismiss",
            json={"handoff_id": created.json()["handoff_id"]},
        )

    assert created.status_code == 200
    assert created.json()["section_heading"] == "3. Methodology"
    assert created.json()["conversation_id"] == "conversation-overlay-7"
    assert created.json()["ai_content"] == "Existing explanation"
    assert current.json()["handoff"]["source_text"].startswith("The LLM")
    assert current.json()["handoff"]["conversation_id"] == "conversation-overlay-7"
    assert service.snapshot() is None
    assert dismissed.json()["handoff"] is None


def test_companion_handoff_defaults_to_context_only_when_no_conversation_exists() -> None:
    service = CompanionHandoffService()

    state = service.create(**_context_payload())

    assert state.conversation_id == ""


class StubCompanionChatService:
    def __init__(self) -> None:
        self.last_call = None

    def status(self):
        return True, "stub-ai", "stub-model", ""

    def send(self, **kwargs):
        self.last_call = kwargs
        return SimpleNamespace(
            session_id=kwargs["session_id"],
            user_message=kwargs["user_message"],
            output_text="context-grounded answer",
            provider="stub-ai",
            model="stub-model",
            request_id=kwargs["request_id"],
            knowledge_enabled=kwargs.get("knowledge_enabled", False),
            knowledge_fallback_reason="",
            evidence=(),
            citations=(),
        )


def test_companion_chat_api_passes_history_and_reading_context_to_service() -> None:
    app = create_app()
    service = StubCompanionChatService()
    app.dependency_overrides[get_companion_chat_service] = lambda: service
    payload = _context_payload()
    payload.update(
        {
            "session_id": "companion-1",
            "user_message": "Why is the GP anchor useful?",
            "history": [
                {"role": "user", "content": "Explain the previous sentence."},
                {"role": "assistant", "content": "It defines the local region."},
            ],
            "request_id": 9,
            "knowledge_enabled": True,
            "knowledge_document_ids": ["doc-1"],
        }
    )

    with TestClient(app) as client:
        response = client.post("/api/companion/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["output_text"] == "context-grounded answer"
    assert service.last_call is not None
    assert service.last_call["section_heading"] == "3. Methodology"
    assert service.last_call["history"][0] == (
        "user",
        "Explain the previous sentence.",
    )
    assert service.last_call["knowledge_enabled"] is True
    assert service.last_call["knowledge_document_ids"] == ("doc-1",)


class StubResearchNoteService:
    def list_recent(self, *, limit: int = 5):
        assert limit == 3
        return (
            SimpleNamespace(
                note_id="note-1",
                display_title="Paper",
                excerpt="Selected passage",
                updated_at="2026-08-20T00:00:00+00:00",
                resource_url="https://example.org/paper",
                resource_title="A Research Paper",
                section_heading="3. Method",
                source_text="Selected passage",
                translated_text="选中段落",
                context_before="Before",
                context_after="After",
                source_kind="browser_selection",
                ai_content="Explanation",
                ai_action="reading_explain",
            ),
        )

    def count(self) -> int:
        return 7


def test_research_note_list_endpoint_exposes_recent_notes_and_total() -> None:
    app = create_app()
    app.dependency_overrides[get_research_note_service] = lambda: StubResearchNoteService()

    with TestClient(app) as client:
        response = client.get("/api/research/notes?limit=3")

    assert response.status_code == 200
    assert response.json()["total"] == 7
    assert response.json()["notes"][0]["note_id"] == "note-1"
    assert response.json()["notes"][0]["resource_title"] == "A Research Paper"
    assert response.json()["notes"][0]["section_heading"] == "3. Method"
    assert response.json()["notes"][0]["conversation_id"] == ""
