from __future__ import annotations

from threading import Event

from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_companion_chat_service,
    get_companion_ownership_service,
    get_conversation_store_service,
)
from backend.main import create_app
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.models.companion_routing import (
    CompanionExecutionPlan,
    CompanionQueryRoute,
    GroundingPolicy,
)
from backend.services.companion_chat_service import (
    CompanionKnowledgeGrounding,
    CompanionPreparedExecution,
)
from backend.services.conversation_store_service import ConversationStoreService


def _payload(
    *,
    conversation_id: str = "",
    request_id: int = 1,
    client_id: str = "main-client",
    client_surface: str = "main",
) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "session_id": "ownership-session",
        "client_id": client_id,
        "client_surface": client_surface,
        "user_message": "Explain the selected passage.",
        "source_text": "The GP identifies a statistically promising region.",
        "translated_text": "GP 识别统计上有希望的区域。",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "https://example.org/paper",
        "resource_title": "Paper",
        "section_heading": "3. Method",
        "context_before": "Before",
        "context_after": "After",
        "source_kind": "browser_selection",
        "history": [],
        "request_id": request_id,
        "context_mode": "reading",
    }


def _receive_type(socket, expected: str) -> dict[str, object]:
    while True:
        event = socket.receive_json()
        if event["type"] == expected:
            return event
        assert event["type"] == "phase"


class BlockingStreamingService:
    provider_name = "stub-ai"
    model = "stub-model"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def prepare_execution(self, **_kwargs):
        return CompanionPreparedExecution(
            plan=CompanionExecutionPlan(
                route=CompanionQueryRoute.GENERAL,
                grounding_policy=GroundingPolicy.NONE,
                use_knowledge=False,
                document_ids=(),
                reason="test_stream_stub",
            ),
            grounding=CompanionKnowledgeGrounding(),
        )

    def stream(self, **_kwargs):
        self.started.set()
        self.release.wait(timeout=5.0)
        yield "answer"


def test_ownership_service_rejects_concurrent_and_duplicate_requests() -> None:
    service = CompanionConversationOwnershipService(
        stale_after_seconds=60,
        duplicate_window_seconds=60,
    )

    first = service.acquire(
        "conversation-1",
        owner_id="main-client",
        owner_surface="main",
        request_id=7,
    )
    busy = service.acquire(
        "conversation-1",
        owner_id="overlay-client",
        owner_surface="overlay",
        request_id=8,
    )

    assert first.acquired is True
    assert busy.acquired is False
    assert busy.reason == "conversation_busy"
    assert busy.lease is not None
    assert busy.lease.owner_surface == "main"

    assert service.release(
        "conversation-1",
        owner_id="main-client",
        request_id=7,
    ) is True

    duplicate = service.acquire(
        "conversation-1",
        owner_id="main-client",
        owner_surface="main",
        request_id=7,
    )
    assert duplicate.acquired is False
    assert duplicate.reason == "duplicate_request"

    next_request = service.acquire(
        "conversation-1",
        owner_id="overlay-client",
        owner_surface="overlay",
        request_id=9,
    )
    assert next_request.acquired is True


def test_backend_allows_only_one_active_stream_per_conversation(tmp_path) -> None:
    app = create_app()
    store = ConversationStoreService(storage_path=tmp_path / "ownership.sqlite3")
    ownership = CompanionConversationOwnershipService()
    streaming = BlockingStreamingService()
    app.dependency_overrides[get_companion_chat_service] = lambda: streaming
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    app.dependency_overrides[get_companion_ownership_service] = lambda: ownership

    with TestClient(app) as client:
        with client.websocket_connect("/ws/companion/chat") as main_socket:
            main_socket.send_json({"type": "start", "request": _payload()})
            accepted = main_socket.receive_json()
            conversation_id = accepted["conversation_id"]
            assert streaming.started.wait(timeout=1.0)

            owner = client.get(
                f"/api/companion/chat/ownership/{conversation_id}"
            ).json()
            assert owner["busy"] is True
            assert owner["owner_surface"] == "main"

            with client.websocket_connect("/ws/companion/chat") as overlay_socket:
                overlay_socket.send_json(
                    {
                        "type": "start",
                        "request": _payload(
                            conversation_id=conversation_id,
                            request_id=2,
                            client_id="overlay-client",
                            client_surface="overlay",
                        ),
                    }
                )
                rejected = overlay_socket.receive_json()

            assert rejected["type"] == "error"
            assert rejected["code"] == "conversation_busy"
            assert "main" in rejected["message"]

            stored_while_busy = store.get(conversation_id)
            assert stored_while_busy is not None
            assert len(stored_while_busy.messages) == 2

            main_socket.send_json({"type": "cancel", "request_id": 1})
            terminal = _receive_type(main_socket, "cancelled")
            assert terminal["type"] == "cancelled"
            streaming.release.set()

        idle = client.get(
            f"/api/companion/chat/ownership/{conversation_id}"
        ).json()
        assert idle["busy"] is False

        retry_streaming = BlockingStreamingService()
        retry_streaming.release.set()
        app.dependency_overrides[get_companion_chat_service] = lambda: retry_streaming
        with client.websocket_connect("/ws/companion/chat") as overlay_retry:
            overlay_retry.send_json(
                {
                    "type": "start",
                    "request": _payload(
                        conversation_id=conversation_id,
                        request_id=3,
                        client_id="overlay-client",
                        client_surface="overlay",
                    ),
                }
            )
            retried = overlay_retry.receive_json()
            assert retried["type"] == "accepted"
            assert _receive_type(overlay_retry, "delta")["type"] == "delta"
            assert _receive_type(overlay_retry, "done")["type"] == "done"
