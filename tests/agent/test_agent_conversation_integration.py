from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_conversation_service import (
    AgentConversationBusyError,
    AgentConversationService,
)
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.conversation_lifecycle_service import ConversationLifecycleService
from backend.services.product_agent_service import ProductAgentService


def _state(
    *,
    message: str,
    source: str,
    conversation_id: str = "",
    request_id: int = 1,
) -> AgentState:
    return AgentState(
        session_id="agent-session-1",
        user_input=message,
        selected_text=source,
        browser_context={
            "conversation_id": conversation_id,
            "client_id": "agent-client-1",
            "client_surface": "main",
            "request_id": request_id,
            "source_language": "en",
            "target_language": "zh-CN",
            "resource_title": "Paper",
            "section_heading": "Method",
            "source_kind": "pdf_uia",
        },
    )


class FakeProductService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **payload):
        self.calls.append(dict(payload))
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="answer",
                user_visible_reason="Answer from the current conversation.",
            ),
            output_text=f"answer-{len(self.calls)}",
            provider="fake",
            model="fake-model",
            request_id=payload.get("request_id", 0),
            tool_result=None,
            route=AgentRouteDecision(
                kind="answer",
                source="semantic_router",
                intent="answer",
            ),
        )


def test_agent_adapter_reuses_durable_conversation_and_injects_prior_history(tmp_path) -> None:
    store = ConversationLifecycleService(storage_path=tmp_path / "chat.sqlite3")
    ownership = CompanionConversationOwnershipService()
    conversation = AgentConversationService(store=store, ownership=ownership)
    product = FakeProductService()
    adapter = ProductAgentRuntimeAdapter(product, conversation_service=conversation)

    first = adapter(_state(message="What does this mean?", source="first selection", request_id=1))
    conversation_id = first.conversation.conversation_id

    assert conversation_id
    assert product.calls[0]["conversation_id"] == conversation_id
    assert product.calls[0]["history"] == ()

    stored_first = store.get(conversation_id)
    assert stored_first is not None
    assert [(item.role, item.content, item.status) for item in stored_first.messages] == [
        ("user", "What does this mean?", "complete"),
        ("assistant", "answer-1", "complete"),
    ]

    second = adapter(
        _state(
            message="How does that relate to this selection?",
            source="second selection",
            conversation_id=conversation_id,
            request_id=2,
        )
    )

    assert second.conversation.conversation_id == conversation_id
    assert product.calls[1]["history"] == (
        ("user", "What does this mean?"),
        ("assistant", "answer-1"),
    )
    stored_second = store.get(conversation_id)
    assert stored_second is not None
    assert stored_second.source_text == "second selection"
    assert len(stored_second.messages) == 4
    assert ownership.snapshot(conversation_id) is None


def test_confirmation_required_discards_temporary_exchange_before_confirmed_retry(tmp_path) -> None:
    store = ConversationLifecycleService(storage_path=tmp_path / "chat.sqlite3")
    ownership = CompanionConversationOwnershipService()
    service = AgentConversationService(store=store, ownership=ownership)
    state = _state(message="保存成笔记", source="important evidence", request_id=5)

    run = service.begin(state)
    service.apply_to_state(state, run)
    state.apply_response({"status": "confirmation_required", "request_id": 5})
    service.complete(run, state)

    stored = store.get(run.conversation_id)
    assert stored is not None
    assert stored.messages == ()
    assert ownership.snapshot(run.conversation_id) is None


def test_agent_conversation_respects_existing_companion_ownership(tmp_path) -> None:
    store = ConversationLifecycleService(storage_path=tmp_path / "chat.sqlite3")
    ownership = CompanionConversationOwnershipService()
    exchange = store.begin_exchange_with_context_mode(
        context_mode="reading",
        session_id="companion-session",
        user_message="existing",
        request_id=1,
        source_text="existing selection",
    )
    store.finalize_message(
        exchange.assistant_message_id,
        status="complete",
        content="existing answer",
    )
    claim = ownership.acquire(
        exchange.conversation_id,
        owner_id="overlay-client",
        owner_surface="overlay",
        request_id=22,
    )
    assert claim.acquired

    service = AgentConversationService(store=store, ownership=ownership)
    state = _state(
        message="Explain this",
        source="new selection",
        conversation_id=exchange.conversation_id,
        request_id=23,
    )

    with pytest.raises(AgentConversationBusyError, match="overlay"):
        service.begin(state)

    assert len(store.get(exchange.conversation_id).messages) == 2  # type: ignore[union-attr]


class UnresolvedRouter:
    def route(self, **_kwargs):
        return AgentRouteDecision()


class CapturingSemanticRouter:
    provider_name = "fake-router"
    model = "router-model"
    prompt_id = "router@1"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def route(self, **kwargs):
        self.calls.append(dict(kwargs))
        return AgentRouteDecision(
            kind="answer",
            source="semantic_router",
            intent="answer",
        )


class EmptyRegistry:
    def list_tools(self):
        return ()


class CapturingChat:
    prompt_id = "chat@1"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            output_text="contextual answer",
            provider="fake-chat",
            model="chat-model",
            request_id=kwargs.get("request_id", 0),
        )


def test_product_agent_passes_history_to_semantic_router_and_synthesis() -> None:
    semantic = CapturingSemanticRouter()
    chat = CapturingChat()
    service = ProductAgentService(
        registry=EmptyRegistry(),  # type: ignore[arg-type]
        chat_service=chat,  # type: ignore[arg-type]
        router=UnresolvedRouter(),  # type: ignore[arg-type]
        semantic_router=semantic,  # type: ignore[arg-type]
    )
    history = (("user", "Earlier question"), ("assistant", "Earlier answer"))

    result = service.run(
        session_id="session-1",
        user_message="What about this?",
        source_text="current selection",
        translated_text="",
        source_language="en",
        target_language="zh-CN",
        resource_url="",
        resource_title="Paper",
        section_heading="Method",
        context_before="",
        context_after="",
        source_kind="pdf_uia",
        history=history,
        request_id=7,
    )

    assert result.output_text == "contextual answer"
    assert semantic.calls[0]["history"] == history
    assert chat.calls[0]["history"] == history
