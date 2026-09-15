from __future__ import annotations

from types import SimpleNamespace

from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan
from backend.services.companion_chat_service import CompanionChatService


class RetrievalStub:
    def __init__(self) -> None:
        self.filters = None
        self.queries: list[str] = []
        self.calls: list[dict] = []

    def retrieve(
        self,
        query,
        *,
        filters=None,
        section_hints=(),
        final_top_k=None,
    ):
        self.filters = filters
        self.queries.append(query)
        self.calls.append(
            {
                "query": query,
                "filters": filters,
                "section_hints": section_hints,
                "final_top_k": final_top_k,
            }
        )
        return RetrievalResult(
            query=query,
            retrieval_strategy="hybrid",
            candidates=[
                RetrievalCandidate(
                    chunk=DocumentChunk(
                        chunk_id="chunk-1",
                        document_id="doc-1",
                        text="Bounded evidence for the answer.",
                        title="Local Paper",
                        source_uri="file:///C:/papers/local.pdf",
                        section_heading="Conclusion",
                        page_number=12,
                        chunk_index=0,
                        end_char=32,
                    ),
                    rank=1,
                    rerank_score=0.9,
                )
            ],
            metadata={"reranker_applied": True},
        )


class PlannerStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def plan(self, query, *, history=()):
        normalized_history = tuple(
            (str(getattr(role, "value", role)), str(content))
            for role, content in history
        )
        self.calls.append((query, normalized_history))
        return RagQueryPlan(
            original_query=query,
            rewritten_query="water tank paper final conclusions findings",
            subqueries=[
                "water tank paper conclusion",
                "water tank paper limitations",
            ],
        )


class ChatStub:
    prompt_id = "chat.stub@1"

    def __init__(self) -> None:
        self.request = None

    def execute(self, request):
        self.request = request
        return SimpleNamespace(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text="Grounded answer [1]",
            provider="stub",
            model="stub-model",
            request_id=request.request_id,
        )


def test_companion_rag_uses_planned_queries_history_document_scope_and_structure() -> None:
    retrieval = RetrievalStub()
    planner = PlannerStub()
    chat = ChatStub()
    service = CompanionChatService(
        chat_service=chat,
        retrieval_service=retrieval,
        query_planner=planner,
    )
    history = (
        ("user", "We are discussing the water tank paper."),
        ("assistant", "It uses MATLAB/Simulink."),
    )

    result = service.send(
        session_id="session-1",
        user_message="What did the authors conclude?",
        context_mode="general",
        history=history,
        knowledge_enabled=True,
        knowledge_document_ids=("doc-1",),
    )

    assert retrieval.filters.document_ids == ["doc-1"]
    assert retrieval.queries == [
        "water tank paper final conclusions findings Conclusion Conclusions concluding remarks final findings",
        "Conclusion Conclusions concluding remarks final findings",
        "water tank paper conclusion",
    ]
    assert planner.calls == [("What did the authors conclude?", history)]
    assert all("conclusion" in call["section_hints"] for call in retrieval.calls)
    assert all(call["final_top_k"] == 10 for call in retrieval.calls)
    assert result.output_text == "Grounded answer [1]"
    assert result.knowledge_enabled is True
    assert result.evidence[0].title == "Local Paper"
    assert result.evidence[0].location == "Page 12 · Section Conclusion"
    assert result.citations[0].label == "[1]"
    assert result.knowledge_fallback_reason == ""
    assert chat.request.tool_name == "search_knowledge_base"
    assert "ALLOWED CITATIONS" in chat.request.tool_context


def test_companion_rag_degrades_without_fabricating_evidence() -> None:
    chat = ChatStub()
    service = CompanionChatService(chat_service=chat)

    result = service.send(
        session_id="session-1",
        user_message="Use my knowledge",
        context_mode="general",
        knowledge_enabled=True,
    )

    assert result.evidence == ()
    assert result.citations == ()
    assert result.knowledge_fallback_reason == "retrieval_unavailable"
    assert "do not cite" in chat.request.tool_context
