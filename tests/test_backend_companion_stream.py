from __future__ import annotations

from time import sleep

from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_companion_chat_service,
    get_conversation_store_service,
)
from backend.main import create_app
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.services.companion_chat_service import CompanionKnowledgeGrounding
from backend.services.conversation_grounding_service import load_message_grounding
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.grounded_synthesis_service import (
    GROUNDING_VERIFICATION_FALLBACK_PREFIX,
)


def _payload(*, request_id: int = 11, conversation_id: str = "") -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "session_id": "companion-stream-1",
        "user_message": "Explain why the GP anchor helps.",
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
        "history": [],
        "request_id": request_id,
    }


class StubStreamingCompanionChatService:
    provider_name = "stub-ai"
    model = "stub-model"

    def stream(self, **_kwargs):
        yield "GP anchors "
        yield "localize the search."


class GroundedStreamingCompanionChatService(StubStreamingCompanionChatService):
    def __init__(self) -> None:
        self.knowledge_history = ()

    def prepare_knowledge(self, _query, _document_ids, *, history=()):
        self.knowledge_history = history
        evidence = AgentEvidenceItem(
            evidence_id="evidence-1",
            source_type="knowledge",
            source_id="doc-1",
            title="Control Paper",
            resource_url="file:///paper.pdf",
            location="Page 8 · Section Stability",
            excerpt="GP anchors localize the search around prior evidence.",
        )
        citation = AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence-1"],
            label="[1]",
        )
        return CompanionKnowledgeGrounding(
            evidence=(evidence,),
            citations=(citation,),
            tool_context="[1] GP anchors localize the search around prior evidence.",
        )

    def stream(self, **_kwargs):
        yield "GP anchors localize the search around prior evidence [1]."


class ParagraphGroundedStreamingCompanionChatService(
    GroundedStreamingCompanionChatService
):
    def stream(self, **_kwargs):
        yield (
            "GP anchors localize the search around prior evidence. "
            "This keeps later refinement focused near the statistically relevant region. "
            "GP anchors localize the search around prior evidence [1]."
        )


class InvalidCitationStreamingCompanionChatService(
    GroundedStreamingCompanionChatService
):
    def stream(self, **_kwargs):
        yield "GP anchors localize the search around prior evidence [9]."


class SlowStreamingCompanionChatService:
    provider_name = "stub-ai"
    model = "stub-model"

    def stream(self, **_kwargs):
        for part in ("one", "two", "three"):
            sleep(0.05)
            yield part


def _grounded_payload(request_id: int) -> dict[str, object]:
    payload = _payload(request_id=request_id)
    payload["knowledge_enabled"] = True
    payload["knowledge_document_ids"] = ["doc-1"]
    return payload


def test_companion_websocket_streams_and_commits_completed_exchange(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app.dependency_overrides[get_companion_chat_service] = (
        lambda: StubStreamingCompanionChatService()
    )
    app.dependency_overrides[get_conversation_store_service] = lambda: store

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as websocket:
            websocket.send_json({"type": "start", "request": _payload()})
            accepted = websocket.receive_json()
            first = websocket.receive_json()
            second = websocket.receive_json()
            done = websocket.receive_json()

    conversation_id = accepted["conversation_id"]
    assert accepted["type"] == "accepted"
    assert accepted["request_id"] == 11
    assert conversation_id
    assert accepted["message_id"]
    assert accepted["user_message_id"]
    assert first == {
        "type": "delta",
        "request_id": 11,
        "conversation_id": conversation_id,
        "message_id": accepted["message_id"],
        "delta": "GP anchors ",
        "accumulated_text": "GP anchors ",
    }
    assert second["accumulated_text"] == "GP anchors localize the search."
    assert done["type"] == "done"
    assert done["output_text"] == "GP anchors localize the search."
    assert done["provider"] == "stub-ai"
    assert done["model"] == "stub-model"
    assert done["knowledge_enabled"] is False
    assert done["evidence"] == []
    assert done["citations"] == []

    stored = store.get(conversation_id)
    assert stored is not None
    assert [message.status for message in stored.messages] == ["complete", "complete"]
    assert stored.messages[-1].content == "GP anchors localize the search."


def test_companion_websocket_persists_completed_knowledge_grounding(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    service = GroundedStreamingCompanionChatService()
    app.dependency_overrides[get_companion_chat_service] = lambda: service
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    payload = _grounded_payload(15)
    payload["history"] = [
        {"role": "user", "content": "We are discussing the water tank paper."},
        {"role": "assistant", "content": "It uses MATLAB/Simulink."},
    ]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as websocket:
            websocket.send_json({"type": "start", "request": payload})
            accepted = websocket.receive_json()
            delta = websocket.receive_json()
            done = websocket.receive_json()

    assert delta["type"] == "delta"
    assert delta["accumulated_text"] == (
        "GP anchors localize the search around prior evidence [1]."
    )
    assert done["type"] == "done"
    assert done["knowledge_enabled"] is True
    assert done["citations"][0]["label"] == "[1]"
    assert len(service.knowledge_history) == 2
    assert service.knowledge_history[0][1] == "We are discussing the water tank paper."
    grounding = load_message_grounding(store.storage_path, accepted["message_id"])
    assert grounding.knowledge_enabled is True
    assert grounding.evidence[0].evidence_id == "evidence-1"
    assert grounding.citations[0].label == "[1]"
    assert done["grounding_verification"]["passed"] is True


def test_companion_websocket_preserves_paragraph_grounded_synthesis(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    service = ParagraphGroundedStreamingCompanionChatService()
    app.dependency_overrides[get_companion_chat_service] = lambda: service
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    payload = _grounded_payload(31)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as websocket:
            websocket.send_json({"type": "start", "request": payload})
            accepted = websocket.receive_json()
            delta = websocket.receive_json()
            done = websocket.receive_json()

    expected = (
        "GP anchors localize the search around prior evidence. "
        "This keeps later refinement focused near the statistically relevant region. "
        "GP anchors localize the search around prior evidence [1]."
    )
    assert delta["type"] == "delta"
    assert delta["accumulated_text"] == expected
    assert done["output_text"] == expected
    assert not done["output_text"].startswith(GROUNDING_VERIFICATION_FALLBACK_PREFIX)
    assert done["grounding_verification"]["passed"] is True
    assert "grounding_verification_failed" not in done["knowledge_fallback_reason"]
    stored = store.get(accepted["conversation_id"])
    assert stored is not None
    assert stored.messages[-1].content == expected


def test_companion_websocket_keeps_invalid_citation_as_hard_fallback(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    service = InvalidCitationStreamingCompanionChatService()
    app.dependency_overrides[get_companion_chat_service] = lambda: service
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    payload = _grounded_payload(32)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as websocket:
            websocket.send_json({"type": "start", "request": payload})
            _accepted = websocket.receive_json()
            delta = websocket.receive_json()
            done = websocket.receive_json()

    assert delta["type"] == "delta"
    assert delta["accumulated_text"].startswith(GROUNDING_VERIFICATION_FALLBACK_PREFIX)
    assert done["output_text"].startswith(GROUNDING_VERIFICATION_FALLBACK_PREFIX)
    assert done["grounding_verification"]["passed"] is False
    assert done["grounding_verification"]["invalid_citation_count"] == 1
    assert "grounding_verification_failed" in done["knowledge_fallback_reason"]


def test_companion_websocket_cancel_commits_terminal_cancelled_message(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    app.dependency_overrides[get_companion_chat_service] = (
        lambda: SlowStreamingCompanionChatService()
    )
    app.dependency_overrides[get_conversation_store_service] = lambda: store

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as websocket:
            websocket.send_json({"type": "start", "request": _payload(request_id=22)})
            accepted = websocket.receive_json()
            websocket.send_json({"type": "cancel", "request_id": 22})
            terminal = websocket.receive_json()

    assert accepted["type"] == "accepted"
    assert terminal == {
        "type": "cancelled",
        "request_id": 22,
        "conversation_id": accepted["conversation_id"],
        "message_id": accepted["message_id"],
    }
    stored = store.get(accepted["conversation_id"])
    assert stored is not None
    assert stored.messages[-1].status == "cancelled"
    assert stored.messages[-1].error_code == "user_cancelled"
