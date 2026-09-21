from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.companion_chat_service import CompanionChatService


class RetrievalProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def retrieve(self, query, **_kwargs):
        self.calls.append(str(query))
        raise RuntimeError("baseline retrieval probe")


class ChatStub:
    prompt_id = "chat.stub@1"

    def execute(self, request):
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="baseline answer",
            provider="stub",
            model="stub-model",
            request_id=request.request_id,
        )


@pytest.mark.xfail(
    strict=True,
    reason="Baseline regression: Knowledge ON currently forces identity queries through RAG.",
)
def test_knowledge_enabled_identity_query_should_skip_retrieval() -> None:
    retrieval = RetrievalProbe()
    service = CompanionChatService(chat_service=ChatStub(), retrieval_service=retrieval)

    service.send(
        session_id="routing-regression",
        user_message="我是谁",
        context_mode="general",
        knowledge_enabled=True,
        knowledge_document_ids=(),
    )

    assert retrieval.calls == []


@pytest.mark.xfail(
    strict=True,
    reason="Baseline regression: knowledge catalog intent currently falls through to vector retrieval.",
)
def test_knowledge_catalog_query_should_skip_vector_retrieval() -> None:
    retrieval = RetrievalProbe()
    service = CompanionChatService(chat_service=ChatStub(), retrieval_service=retrieval)

    service.send(
        session_id="routing-regression",
        user_message="资料库里有什么？",
        context_mode="general",
        knowledge_enabled=True,
        knowledge_document_ids=(),
    )

    assert retrieval.calls == []
