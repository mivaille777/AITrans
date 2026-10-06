from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan, RagQueryPlanner
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
        **channels,
    ):
        self.filters = filters
        self.queries.append(query)
        self.calls.append(
            {
                "query": query,
                "filters": filters,
                "section_hints": section_hints,
                "final_top_k": final_top_k,
                "channels": channels,
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


@pytest.mark.parametrize("document_ids", [("doc-1",), ("doc-1", "doc-2"), ()])
def test_only_single_document_scope_allows_content_focused_planning(document_ids):
    class Client:
        payload = None

        def complete(self, **kwargs):
            self.payload = json.loads(kwargs["user_prompt"])
            return json.dumps(
                {"rewritten_query": "Why constrain PID updates?", "subqueries": []}
            )

    client = Client()
    planner = RagQueryPlanner(
        text_service=SimpleNamespace(provider=SimpleNamespace(client=client))
    )
    retrieval = RetrievalStub()
    query = "水箱论文为何限制 PID 更新？"
    CompanionChatService(
        retrieval_service=retrieval, query_planner=planner
    ).prepare_knowledge(
        query,
        document_ids,
    )
    assert client.payload["policy"]["single_document_scope"] == (len(document_ids) == 1)
    assert client.payload["current_query"] == (
        "为何限制 PID 更新？" if len(document_ids) == 1 else query
    )
    assert retrieval.queries[0] == query
    assert all(
        (call["filters"].document_ids if call["filters"] else []) == list(document_ids)
        for call in retrieval.calls
    )


def test_rewrite_cannot_introduce_a_section_constraint_from_answer_format():
    retrieval = RetrievalStub()
    service = CompanionChatService(
        retrieval_service=retrieval,
        query_planner=PlannerStub(),
        rag_router_enabled=True,
    )
    query = "水箱控制论文研究了什么系统？请给出一句话结论并附引用。"

    service.prepare_knowledge(query, ("doc-1",))

    assert retrieval.queries[0] == query
    assert all(not call["section_hints"] for call in retrieval.calls)
    assert (
        "Conclusion Conclusions concluding remarks final findings"
        not in retrieval.queries
    )


def test_companion_rag_uses_planned_queries_history_document_scope_and_structure() -> (
    None
):
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
        "What did the authors conclude?",
        "water tank paper final conclusions findings Conclusion Conclusions concluding remarks final findings",
        "Conclusion Conclusions concluding remarks final findings",
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


def test_rewrite_and_router_can_be_disabled_independently():
    for rewrite_enabled in (False, True):
        for router_enabled in (False, True):
            retrieval, planner = RetrievalStub(), PlannerStub()
            service = CompanionChatService(
                retrieval_service=retrieval,
                query_planner=planner,
                rag_rewrite_enabled=rewrite_enabled,
                rag_router_enabled=router_enabled,
            )
            grounding = service.prepare_knowledge("Explain the mechanism", ("doc-1",))
            assert retrieval.queries[0] == "Explain the mechanism"
            assert all(
                call["filters"].document_ids == ["doc-1"] for call in retrieval.calls
            )
            assert len(planner.calls) == int(rewrite_enabled)
            assert len(retrieval.calls) <= 3
            assert bool(retrieval.calls[0]["channels"]) is router_enabled
            assert (
                grounding.debug_metadata["query_plan"]["original_query"]
                == "Explain the mechanism"
            )
            assert grounding.debug_metadata["query_route"]["enabled"] is router_enabled


def test_keyword_budget_keeps_literal_acronym_without_model_expansion():
    retrieval, planner = RetrievalStub(), PlannerStub()
    service = CompanionChatService(
        retrieval_service=retrieval, query_planner=planner, rag_router_enabled=True
    )
    result = service.prepare_knowledge("What is GP?", ("doc-1",))
    assert retrieval.queries == ["What is GP?"]
    assert planner.calls == []
    assert result.debug_metadata["query_route"]["query_type"] == "keyword"


def test_planner_exception_falls_back_to_original_with_same_scope():
    class FailingPlanner:
        def plan(self, *args, **kwargs):
            raise TimeoutError("rewrite deadline")

    retrieval = RetrievalStub()
    result = CompanionChatService(
        retrieval_service=retrieval, query_planner=FailingPlanner()
    ).prepare_knowledge("Explain this mechanism", ("doc-1",))
    assert retrieval.queries == ["Explain this mechanism"]
    assert retrieval.filters.document_ids == ["doc-1"]
    assert "rewrite deadline" in result.debug_metadata["query_plan"]["fallback_reason"]


def test_router_scope_drift_falls_back_to_original_before_retrieval():
    from backend.rag.query_router import RagQueryRoute

    class BadRouter:
        def route(self, *args, **kwargs):
            return RagQueryRoute("semantic", "bad", True, ("private-B",))

    retrieval = RetrievalStub()
    result = CompanionChatService(
        retrieval_service=retrieval,
        query_planner=PlannerStub(),
        rag_query_router=BadRouter(),
    ).prepare_knowledge("Explain this mechanism", ("doc-1",))
    assert retrieval.queries == ["Explain this mechanism"]
    assert retrieval.filters.document_ids == ["doc-1"]
    assert result.debug_metadata["router_fallback_reason"]


def test_keyword_channel_failure_retries_original_with_existing_channels_and_scope():
    class FailedKeyword(RetrievalStub):
        def retrieve(self, query, **kwargs):
            if kwargs.get("dense_enabled") is False:
                self.queries.append(query)
                raise OSError("BM25 unavailable")
            return super().retrieve(query, **kwargs)

    retrieval = FailedKeyword()
    result = CompanionChatService(
        retrieval_service=retrieval, rag_router_enabled=True
    ).prepare_knowledge("What is GP?", ("doc-1",))
    assert retrieval.queries == ["What is GP?", "What is GP?"]
    assert retrieval.filters.document_ids == ["doc-1"]
    assert result.evidence
    assert result.debug_metadata["router_fallback_reason"] == "routed_channels_failed"
    assert "BM25 unavailable" in result.fallback_reason


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


class CatalogLibraryStub:
    def __init__(self) -> None:
        self.calls = 0

    def list_documents(self):
        self.calls += 1
        return [
            SimpleNamespace(
                document_id="doc-1",
                title="Control Paper",
                status=SimpleNamespace(value="ready"),
                chunk_ids=["c1", "c2"],
                section_count=7,
                source_uri="file:///private/path/control.pdf",
                content_hash="should-not-leak",
                embedding_model="private-model",
            ),
            SimpleNamespace(
                document_id="doc-2",
                title="Notes",
                status=SimpleNamespace(value="failed"),
                chunk_ids=[],
                section_count=2,
                source_uri="file:///private/path/notes.md",
                content_hash="should-not-leak",
                embedding_model="private-model",
            ),
        ]


class CatalogRetrievalProbe:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("catalog route must not call retrieval")


def test_companion_catalog_route_renders_manifest_without_retrieval_or_llm() -> None:
    library = CatalogLibraryStub()
    retrieval = CatalogRetrievalProbe()
    chat = ChatStub()
    service = CompanionChatService(
        chat_service=chat,
        retrieval_service=retrieval,
        knowledge_library_service=library,
    )

    result = service.send(
        session_id="catalog-1",
        user_message="资料库里有什么？",
        context_mode="general",
        knowledge_enabled=True,
        knowledge_document_ids=(),
    )

    assert library.calls == 1
    assert retrieval.calls == 0
    assert result.provider == "local"
    assert result.model == "deterministic"
    assert "Control Paper" in result.output_text
    assert "Notes" in result.output_text
    assert "Chunks：2" in result.output_text
    assert "Sections：7" in result.output_text
    assert "private/path" not in result.output_text
    assert "should-not-leak" not in result.output_text
    assert "private-model" not in result.output_text
