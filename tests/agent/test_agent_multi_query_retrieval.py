from __future__ import annotations

from types import SimpleNamespace

from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import RagQueryPlan
from backend.services.agent_tool_registry import AgentToolRegistry


class QueryPlanner:
    def __init__(self, plan: RagQueryPlan) -> None:
        self.plan_result = plan
        self.calls: list[str] = []

    def plan(self, query: str) -> RagQueryPlan:
        self.calls.append(query)
        return self.plan_result


class Retrieval:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def retrieve(self, query: str, *, filters=None) -> RetrievalResult:
        self.calls.append(query)
        shared = self._candidate("shared", query, 1)
        unique = self._candidate(f"unique-{len(self.calls)}", query, 2)
        return RetrievalResult(
            query=query,
            candidates=[shared, unique],
            retrieval_strategy="hybrid",
            elapsed_ms=1.0,
        )

    @staticmethod
    def _candidate(chunk_id: str, query: str, rank: int) -> RetrievalCandidate:
        return RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id=chunk_id,
                document_id=f"doc-{chunk_id}",
                text=f"{query}: {chunk_id}",
                chunk_index=rank - 1,
                start_char=0,
                end_char=20,
            ),
            rerank_score=1.0 / rank,
            rank=rank,
        )


def _registry(retrieval: Retrieval, planner: QueryPlanner) -> AgentToolRegistry:
    return AgentToolRegistry(
        translation_service=SimpleNamespace(),
        quick_action_service=SimpleNamespace(),
        research_note_service=SimpleNamespace(),
        retrieval_service=retrieval,
        query_planner=planner,
    )


def test_agent_runs_bounded_rewritten_query_and_subqueries_then_merges_one_evidence_set() -> None:
    original = "论文里为什么 M10 比 C8 好？"
    plan = RagQueryPlan(
        original_query=original,
        rewritten_query="M10 and C8 comparison",
        subqueries=["M10 mechanism", "C8 mechanism", "M10 vs C8 results"],
    )
    planner = QueryPlanner(plan)
    retrieval = Retrieval()
    registry = _registry(retrieval, planner)

    result = registry.execute(
        "search_knowledge_base",
        query=original,
        top_k=3,
        request_id=44,
    )

    assert planner.calls == [original]
    assert retrieval.calls == list(plan.retrieval_queries)
    assert retrieval.calls == [
        "M10 and C8 comparison",
        "M10 mechanism",
        "C8 mechanism",
    ]
    assert result.data is not None
    assert result.data["query"] == original
    assert result.data["query_plan"] == plan.model_dump(mode="json")
    chunk_ids = [item["chunk_id"] for item in result.data["results"]]
    assert chunk_ids == ["shared", "unique-1", "unique-2"]
    assert len(chunk_ids) == len(set(chunk_ids)) == 3
    assert len(result.data["evidence"]) == 3
    assert len(result.data["citations"]) == 3


def test_fallback_plan_keeps_rag_on_original_query() -> None:
    original = "Compare M10 versus C8"
    planner = QueryPlanner(
        RagQueryPlan(
            original_query=original,
            rewritten_query=original,
            subqueries=[],
        )
    )
    retrieval = Retrieval()

    result = _registry(retrieval, planner).execute(
        "search_knowledge_base",
        query=original,
        top_k=2,
    )

    assert retrieval.calls == [original]
    assert result.data is not None
    assert len(result.data["results"]) == 2
