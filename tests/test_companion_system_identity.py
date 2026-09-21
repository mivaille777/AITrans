from __future__ import annotations

from types import SimpleNamespace

from app.ai.chat.service import CHAT_SYSTEM_PROMPT
from app.ai.chat.system_context import SYSTEM_CONTEXT
from backend.models.companion_routing import CompanionQueryRoute
from backend.services.companion_chat_service import CompanionChatService


class RetrievalProbe:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("identity route must not retrieve")


class ChatProbe:
    prompt_id = "chat.identity-probe@1"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="provider answer",
            provider="stub",
            model="stub-model",
            request_id=request.request_id,
        )


def test_system_identity_uses_canonical_product_profile_without_llm_or_rag() -> None:
    retrieval = RetrievalProbe()
    chat = ChatProbe()
    service = CompanionChatService(
        chat_service=chat,
        retrieval_service=retrieval,
    )

    result = service.send(
        session_id="identity-1",
        user_message="你是谁？",
        context_mode="general",
        knowledge_enabled=True,
        knowledge_document_ids=(),
    )

    assert result.provider == "local"
    assert result.model == "deterministic"
    assert "AITrans" in result.output_text
    assert retrieval.calls == 0
    assert chat.calls == 0


def test_identity_route_is_stable_with_or_without_knowledge_enabled() -> None:
    service = CompanionChatService()
    off = service.prepare_execution(
        query="我是谁",
        knowledge_enabled=False,
        context_mode="general",
    )
    on = service.prepare_execution(
        query="我是谁",
        knowledge_enabled=True,
        context_mode="general",
    )

    assert off.plan.route is CompanionQueryRoute.SYSTEM_IDENTITY
    assert on.plan.route is CompanionQueryRoute.SYSTEM_IDENTITY
    assert off.direct_output_text == on.direct_output_text
    assert "AITrans" in off.direct_output_text


def test_general_chat_system_prompt_uses_same_canonical_identity() -> None:
    assert SYSTEM_CONTEXT.assistant_name in CHAT_SYSTEM_PROMPT
    assert SYSTEM_CONTEXT.product_name in CHAT_SYSTEM_PROMPT
    assert SYSTEM_CONTEXT.prompt_identity in CHAT_SYSTEM_PROMPT
    assert "AITranslator" not in CHAT_SYSTEM_PROMPT
