from __future__ import annotations

import json
from types import SimpleNamespace

from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.query_planner import (
    MAX_RAG_RETRIEVAL_QUERIES,
    MAX_RAG_SUBQUERIES,
    RagQueryPlan,
    RagQueryPlanner,
    merge_query_results,
)


class Client:
    def __init__(self, response: str = "", failure: Exception | None = None) -> None:
        self.response = response
        self.failure = failure
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.failure is not None:
            raise self.failure
        return self.response


def _planner(client: Client) -> RagQueryPlanner:
    return RagQueryPlanner(
        text_service=SimpleNamespace(
            provider=SimpleNamespace(client=client),
            provider_name="fake",
            model="planner-model",
        )
    )


def _candidate(chunk_id: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            text=f"Evidence for {chunk_id}",
            chunk_index=rank - 1,
            start_char=0,
            end_char=20,
        ),
        rerank_score=1.0 / rank,
        rank=rank,
    )


def test_complex_query_returns_typed_bounded_plan() -> None:
    client = Client(
        json.dumps(
            {
                "original_query": "model supplied value is ignored",
                "rewritten_query": "M10 and C8 comparison",
                "subqueries": [
                    "M10 mechanism",
                    "C8 mechanism",
                    "M10 vs C8 results",
                    "must be truncated",
                ],
            }
        )
    )
    planner = _planner(client)

    plan = planner.plan("论文里为什么 M10 比 C8 好？")

    assert isinstance(plan, RagQueryPlan)
    assert plan.original_query == "论文里为什么 M10 比 C8 好？"
    assert plan.rewritten_query == "M10 and C8 comparison"
    assert plan.subqueries == [
        "M10 mechanism",
        "C8 mechanism",
        "M10 vs C8 results",
    ]
    assert len(plan.subqueries) == MAX_RAG_SUBQUERIES
    assert plan.retrieval_queries == (
        "M10 and C8 comparison",
        "M10 mechanism",
        "C8 mechanism",
    )
    assert len(plan.retrieval_queries) == MAX_RAG_RETRIEVAL_QUERIES
    assert planner.prompt_id.endswith("@1.3.0")
    assert len(client.calls) == 1
    prompt = json.loads(client.calls[0]["user_prompt"])
    assert prompt["policy"]["recursive_decomposition"] is False
    assert prompt["policy"]["standalone_rewrite"] is True
    assert prompt["policy"]["preserve_document_structure"] is True
    assert "References/Bibliography" in client.calls[0]["system_prompt"]
    assert "Table" in client.calls[0]["system_prompt"]
    assert "Figure" in client.calls[0]["system_prompt"]
    assert "Equation" in client.calls[0]["system_prompt"]
    assert "Formula" in client.calls[0]["system_prompt"]


def test_simple_query_is_rewritten_before_retrieval() -> None:
    client = Client(
        json.dumps(
            {
                "original_query": "ignored",
                "rewritten_query": "M10 definition and role",
                "subqueries": [],
            }
        )
    )

    plan = _planner(client).plan("What is M10?")

    assert plan.original_query == "What is M10?"
    assert plan.rewritten_query == "M10 definition and role"
    assert plan.retrieval_queries == ("M10 definition and role",)
    assert len(client.calls) == 1
    prompt = json.loads(client.calls[0]["user_prompt"])
    assert prompt["current_query"] == "What is M10?"
    assert prompt["policy"]["decompose"] is False


def test_follow_up_query_uses_bounded_history_to_resolve_document_reference() -> None:
    client = Client(
        json.dumps(
            {
                "original_query": "ignored",
                "rewritten_query": (
                    "An experiment of using a large language model to control a water "
                    "tank system final conclusions findings limitations discussion future work"
                ),
                "subqueries": [
                    "water tank LLM paper conclusion final findings",
                    "water tank LLM paper limitations future work",
                ],
            }
        )
    )
    history = (
        (
            "user",
            "Wen的论文《An experiment of using a large language model to control a water tank system》采用了什么仿真模型？",
        ),
        ("assistant", "该论文使用 MATLAB/Simulink 与 Python 协同仿真。"),
    )

    plan = _planner(client).plan("他最后的观点是什么？", history=history)

    assert "final conclusions" in plan.rewritten_query
    assert len(plan.retrieval_queries) == 3
    prompt = json.loads(client.calls[0]["user_prompt"])
    assert prompt["current_query"] == "他最后的观点是什么？"
    assert prompt["conversation_history"][0]["role"] == "user"
    assert "water tank system" in prompt["conversation_history"][0]["content"]
    assert prompt["policy"]["resolve_follow_up_references"] is True
    assert prompt["policy"]["preserve_document_structure"] is True


def test_planner_failure_and_malformed_output_fall_back_to_original_query() -> None:
    query = "Compare M10 versus C8"

    failed = _planner(Client(failure=OSError("planner unavailable"))).plan(query)
    malformed = _planner(Client(response="not-json")).plan(query)

    for plan in (failed, malformed):
        assert plan.original_query == query
        assert plan.rewritten_query == query
        assert plan.subqueries == []
        assert plan.retrieval_queries == (query,)


def test_multi_query_merge_dedupes_chunks_and_applies_result_limit() -> None:
    results = [
        RetrievalResult(
            query="M10",
            candidates=[_candidate("shared", 1), _candidate("m10", 2)],
            retrieval_strategy="hybrid",
            elapsed_ms=2.0,
            metadata={"reranker_applied": True},
        ),
        RetrievalResult(
            query="C8",
            candidates=[_candidate("shared", 1), _candidate("c8", 2)],
            retrieval_strategy="hybrid",
            elapsed_ms=3.0,
            metadata={"reranker_applied": True},
        ),
    ]

    merged = merge_query_results("M10 versus C8", results, limit=2)

    assert merged.query == "M10 versus C8"
    assert merged.retrieval_strategy == "multi-query"
    assert [item.chunk.chunk_id for item in merged.candidates] == ["shared", "c8"]
    assert len({item.chunk.chunk_id for item in merged.candidates}) == 2
    assert merged.metadata["retrieval_queries"] == ["M10", "C8"]
    assert merged.metadata["multi_query_fusion"] is True
    assert merged.metadata["reranker_applied"] is True
