from __future__ import annotations

from backend.agent_core.context import ReadingContextProvider
from backend.agent_core.state import AgentState
from backend.models.agent_tools import AgentRunRequest
from backend.services.agent_conversation_service import AgentConversationService
from backend.services.companion_chat_service import CompanionChatService
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.conversation_lifecycle_service import ConversationLifecycleService


class CountingResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve_for_text(self, _source_text: str):
        self.calls += 1
        return None


def test_general_agent_request_accepts_empty_source_text() -> None:
    request = AgentRunRequest(
        user_message="Introduce yourself",
        context_mode="general",
    )

    assert request.source_text == ""
    assert request.context_mode == "general"


def test_agent_context_provider_does_not_resolve_cached_reading_for_general_mode() -> None:
    resolver = CountingResolver()
    provider = ReadingContextProvider(resolver)
    state = AgentState(
        user_input="Introduce yourself",
        selected_text="",
        browser_context={"context_mode": "general"},
    )

    context = provider(state)

    assert resolver.calls == 0
    assert context["context_mode"] == "general"
    assert context["source_text"] == ""


def test_companion_does_not_repopulate_empty_agent_source_from_reading_cache() -> None:
    resolver = CountingResolver()
    service = CompanionChatService(reading_resolver=resolver)

    payload = service._with_resolved_reading(
        {
            "context_mode": "reading",
            "source_text": "",
            "resource_title": "",
            "source_kind": "desktop",
        }
    )

    assert resolver.calls == 0
    assert payload["source_text"] == ""


def test_empty_reading_payload_builds_context_free_chat_request() -> None:
    request = CompanionChatService._build_request(
        session_id="agent-workspace-test",
        user_message="Analyze the knowledge base",
        context_mode="reading",
        source_text="",
        resource_title="",
        source_kind="desktop",
    )

    assert request.context.source_text == ""
    assert request.context.translated_text == ""
    assert request.context.reading.has_context is False


def test_real_reading_source_still_uses_reading_resolver() -> None:
    resolver = CountingResolver()
    service = CompanionChatService(reading_resolver=resolver)

    payload = service._with_resolved_reading(
        {
            "context_mode": "reading",
            "source_text": "Selected paper passage",
        }
    )

    assert resolver.calls == 1
    assert payload["source_text"] == "Selected paper passage"


def test_knowledge_agent_conversation_is_persisted_without_stale_reading_context(tmp_path) -> None:
    store = ConversationLifecycleService(storage_path=tmp_path / "chat.sqlite3")
    ownership = CompanionConversationOwnershipService()
    service = AgentConversationService(store=store, ownership=ownership)
    state = AgentState(
        session_id="agent-knowledge-test",
        user_input="Analyze the knowledge base",
        selected_text="",
        browser_context={
            "context_mode": "knowledge",
            "request_id": 1,
            "resource_title": "stale-reading-image.png",
            "section_heading": "stale selection",
            "source_kind": "desktop",
        },
    )

    run = service.begin(state)
    service.apply_to_state(state, run)
    state.apply_response(
        {
            "status": "completed",
            "output_text": "Knowledge answer",
            "provider": "fake",
            "model": "fake-model",
            "request_id": 1,
        }
    )
    service.complete(run, state)

    stored = store.get(run.conversation_id)
    assert stored is not None
    assert store.context_mode(run.conversation_id) == "general"
    assert stored.source_text == ""
    assert stored.resource_title == ""
    assert stored.section_heading == ""
