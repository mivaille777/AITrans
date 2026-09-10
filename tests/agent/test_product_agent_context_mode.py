from __future__ import annotations

from types import SimpleNamespace

from backend.models.agent_runtime import AgentRouteDecision
from backend.services.product_agent_service import ProductAgentService


class EmptyRegistry:
    def list_tools(self):
        return ()


class AnswerRouter:
    def route(self, **_kwargs):
        return AgentRouteDecision(
            kind="answer",
            source="deterministic",
            intent="answer",
            user_visible_reason="Answer directly.",
        )


class CapturingChat:
    prompt_id = "chat@test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            output_text="answer",
            provider="fake",
            model="fake-model",
            request_id=kwargs.get("request_id", 0),
        )


def _run(service: ProductAgentService, *, context_mode: str, source_text: str) -> None:
    service.run(
        session_id="agent-context-test",
        context_mode=context_mode,
        user_message="Test context routing",
        source_text=source_text,
        translated_text="",
        source_language="en",
        target_language="zh-CN",
        resource_url="",
        resource_title="Paper" if source_text else "",
        section_heading="",
        context_before="",
        context_after="",
        source_kind="pdf_uia" if source_text else "desktop",
        history=(),
        request_id=1,
    )


def test_knowledge_synthesis_uses_general_chat_context() -> None:
    chat = CapturingChat()
    service = ProductAgentService(
        registry=EmptyRegistry(),  # type: ignore[arg-type]
        chat_service=chat,  # type: ignore[arg-type]
        router=AnswerRouter(),  # type: ignore[arg-type]
    )

    _run(service, context_mode="knowledge", source_text="")

    assert chat.calls[0]["context_mode"] == "general"
    assert chat.calls[0]["source_text"] == ""


def test_reading_synthesis_preserves_reading_chat_context() -> None:
    chat = CapturingChat()
    service = ProductAgentService(
        registry=EmptyRegistry(),  # type: ignore[arg-type]
        chat_service=chat,  # type: ignore[arg-type]
        router=AnswerRouter(),  # type: ignore[arg-type]
    )

    _run(service, context_mode="reading", source_text="Selected passage")

    assert chat.calls[0]["context_mode"] == "reading"
    assert chat.calls[0]["source_text"] == "Selected passage"


def test_translation_synthesis_keeps_selected_reading_context() -> None:
    chat = CapturingChat()
    service = ProductAgentService(
        registry=EmptyRegistry(),  # type: ignore[arg-type]
        chat_service=chat,  # type: ignore[arg-type]
        router=AnswerRouter(),  # type: ignore[arg-type]
    )

    _run(service, context_mode="translation", source_text="Selected passage")

    assert chat.calls[0]["context_mode"] == "reading"
