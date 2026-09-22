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
from backend.services.conversation_lifecycle_service import ConversationLifecycleService


def _request(
    *,
    conversation_id: str = "",
    request_id: int,
    client_id: str,
    client_surface: str,
    message: str,
) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "session_id": "batch-4-integration",
        "client_id": client_id,
        "client_surface": client_surface,
        "user_message": message,
        "source_text": "GP provides the statistical anchor and the LLM refines locally.",
        "translated_text": "GP 提供统计锚点，LLM 进行局部细化。",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "file:///paper.pdf",
        "resource_title": "Control paper",
        "section_heading": "3.4 Local refinement",
        "context_before": "Before",
        "context_after": "After",
        "source_kind": "pdf_uia",
        "context_mode": "reading",
        "history": [],
        "request_id": request_id,
    }


class ControlledStreamingService:
    provider_name = "stub-ai"
    model = "stub-model"

    def __init__(self) -> None:
        self.block = False
        self.started = Event()
        self.release = Event()

    def reset_gate(self, *, block: bool) -> None:
        self.block = block
        self.started.clear()
        self.release.clear()
        if not block:
            self.release.set()

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
        yield "grounded answer"


def test_batch4_companion_conversation_lifecycle_across_windows(tmp_path) -> None:
    app = create_app()
    store = ConversationLifecycleService(storage_path=tmp_path / "batch4.sqlite3")
    ownership = CompanionConversationOwnershipService()
    streaming = ControlledStreamingService()
    app.dependency_overrides[get_conversation_store_service] = lambda: store
    app.dependency_overrides[get_companion_ownership_service] = lambda: ownership
    app.dependency_overrides[get_companion_chat_service] = lambda: streaming

    with TestClient(app) as client:
        # Overlay creates and completes the durable conversation.
        streaming.reset_gate(block=False)
        with client.websocket_connect("/ws/companion/chat") as overlay:
            overlay.send_json(
                {
                    "type": "start",
                    "request": _request(
                        request_id=1,
                        client_id="overlay-client",
                        client_surface="overlay",
                        message="Explain this selection.",
                    ),
                }
            )
            overlay_accepted = overlay.receive_json()
            assert overlay_accepted["type"] == "accepted"
            assert overlay.receive_json()["type"] == "delta"
            assert overlay.receive_json()["type"] == "done"

        conversation_id = overlay_accepted["conversation_id"]
        persisted = client.get(f"/api/conversations/{conversation_id}")
        assert persisted.status_code == 200
        assert [item["status"] for item in persisted.json()["messages"]] == [
            "complete",
            "complete",
        ]

        # Main resumes that exact conversation and becomes the execution owner.
        streaming.reset_gate(block=True)
        with client.websocket_connect("/ws/companion/chat") as main:
            main.send_json(
                {
                    "type": "start",
                    "request": _request(
                        conversation_id=conversation_id,
                        request_id=2,
                        client_id="main-client",
                        client_surface="main",
                        message="Continue in the main window.",
                    ),
                }
            )
            main_accepted = main.receive_json()
            assert main_accepted["type"] == "accepted"
            assert streaming.started.wait(timeout=1.0)

            status = client.get(
                f"/api/companion/chat/ownership/{conversation_id}"
            )
            assert status.status_code == 200
            assert status.json()["busy"] is True
            assert status.json()["owner_surface"] == "main"

            # Overlay cannot race a second generation into the same conversation.
            with client.websocket_connect("/ws/companion/chat") as overlay_race:
                overlay_race.send_json(
                    {
                        "type": "start",
                        "request": _request(
                            conversation_id=conversation_id,
                            request_id=3,
                            client_id="overlay-client",
                            client_surface="overlay",
                            message="Race from overlay.",
                        ),
                    }
                )
                rejected = overlay_race.receive_json()
            assert rejected["type"] == "error"
            assert rejected["code"] == "conversation_busy"

            # Mutations that would invalidate the active stream are also blocked.
            context_conflict = client.patch(
                f"/api/conversations/{conversation_id}/context",
                json={"context_mode": "general"},
            )
            rewind_conflict = client.post(
                f"/api/conversations/{conversation_id}/rewind",
                json={"user_message_id": overlay_accepted["user_message_id"]},
            )
            delete_conflict = client.delete(f"/api/conversations/{conversation_id}")
            assert context_conflict.status_code == 409
            assert rewind_conflict.status_code == 409
            assert delete_conflict.status_code == 409

            main.send_json({"type": "cancel", "request_id": 2})
            assert main.receive_json()["type"] == "cancelled"
            streaming.release.set()

        # Once the lease is released, normal conversation mutation resumes.
        idle = client.get(f"/api/companion/chat/ownership/{conversation_id}")
        assert idle.json()["busy"] is False

        detached = client.patch(
            f"/api/conversations/{conversation_id}/context",
            json={"context_mode": "general"},
        )
        assert detached.status_code == 200
        assert detached.json()["context_mode"] == "general"

        rewound = client.post(
            f"/api/conversations/{conversation_id}/rewind",
            json={"user_message_id": main_accepted["user_message_id"]},
        )
        assert rewound.status_code == 200
        assert len(rewound.json()["messages"]) == 2

        deleted = client.delete(f"/api/conversations/{conversation_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
