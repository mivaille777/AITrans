from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_tools.knowledge import KnowledgeSearchResultData
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.services.agent_tool_registry import AgentToolRegistry


def _candidate(index: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=f"chunk-{index}",
            document_id=f"doc-{index}",
            text=f"Knowledge excerpt {index}",
            title=f"Paper {index}",
            section_heading="Results",
            page_number=index,
            chunk_index=index - 1,
            start_char=0,
            end_char=20,
            source_uri=f"file:///paper-{index}.pdf",
        ),
        dense_score=0.8 - index / 100,
        fusion_score=0.03 - index / 1000,
        rerank_score=0.9 - index / 100,
        rank=index,
        metadata={"retrieval": "hybrid"},
    )


class StubRetrievalService:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, object]] = []

    def retrieve(self, query: str, *, filters=None) -> RetrievalResult:
        self.calls.append((query, filters))
        if self.failure is not None:
            raise self.failure
        return RetrievalResult(
            query=query,
            candidates=[_candidate(1), _candidate(2)],
            retrieval_strategy="hybrid",
            elapsed_ms=12.5,
            metadata={"fallback_reason": ""},
        )


def _registry(retrieval_service: StubRetrievalService) -> AgentToolRegistry:
    return AgentToolRegistry(
        translation_service=SimpleNamespace(),
        quick_action_service=SimpleNamespace(),
        research_note_service=SimpleNamespace(),
        retrieval_service=retrieval_service,
    )


def test_registry_lists_read_and_confirmed_write_knowledge_tools_last() -> None:
    registry = _registry(StubRetrievalService())

    names = [tool.name for tool in registry.list_tools()]
    search_tool = registry.get_tool("search_knowledge_base")
    save_tool = registry.get_tool("save_knowledge_card")

    assert names[-2:] == ["search_knowledge_base", "save_knowledge_card"]
    assert names[:11] == [
        "inspect_reading_context",
        "translate_selection",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "polish_selection",
        "save_research_note",
        "list_research_notes",
        "search_research_notes",
        "get_research_note",
        "update_research_note",
    ]
    assert names[11:-2] == [
        "define_terms",
        "analyze_equation",
        "summarize_current_section",
    ]
    assert search_tool is not None
    assert search_tool.category == "knowledge"
    assert search_tool.effect == "read"
    assert search_tool.requires_reading_context is False
    assert search_tool.requires_confirmation is False
    assert set(search_tool.input_schema) == {"query", "document_scope"}
    assert registry.allows_safe_retry(search_tool.name) is True

    assert save_tool is not None
    assert save_tool.category == "knowledge"
    assert save_tool.effect == "write"
    assert save_tool.requires_reading_context is False
    assert save_tool.requires_confirmation is True
    assert save_tool.input_schema == {}
    assert registry.allows_safe_retry(save_tool.name) is False


def test_search_maps_typed_results_without_embedding_vectors() -> None:
    retrieval = StubRetrievalService()
    registry = _registry(retrieval)

    result = registry.execute(
        "search_knowledge_base",
        query="Gaussian processes",
        document_ids=["doc-1"],
        document_scope="doc-2, doc-1",
        top_k=1,
        request_id=17,
    )

    assert result.request_id == 17
    assert result.data is not None
    assert KnowledgeSearchResultData.model_validate(result.data)
    assert result.data["retrieval_strategy"] == "hybrid"
    assert len(result.data["results"]) == 1
    assert result.data["results"][0]["chunk_id"] == "chunk-1"
    assert "vector" not in result.data["results"][0]
    assert result.data["evidence"][0]["evidence_id"] == "evidence:chunk-1"
    assert result.data["citations"][0] == {
        "citation_id": "citation-1",
        "evidence_ids": ["evidence:chunk-1"],
        "label": "[1]",
    }
    filters = retrieval.calls[0][1]
    assert filters is not None
    assert filters.document_ids == ["doc-1", "doc-2"]


def test_planner_rejects_unknown_knowledge_arguments() -> None:
    registry = _registry(StubRetrievalService())

    assert registry.validate_planner_arguments(
        "search_knowledge_base",
        {"query": "control", "document_scope": "doc-a,doc-b"},
    ) == {"query": "control", "document_scope": "doc-a,doc-b"}
    with pytest.raises(ValueError, match="outside its authority"):
        registry.validate_planner_arguments(
            "search_knowledge_base",
            {"query": "control", "document_ids": ["doc-a"]},
        )


def test_knowledge_result_contract_rejects_invalid_data() -> None:
    definition = _registry(StubRetrievalService()).get_definition(
        "search_knowledge_base"
    )
    assert definition is not None

    with pytest.raises(ValueError, match="invalid structured result"):
        definition.normalize_result_data(
            {
                "query": "control",
                "retrieval_strategy": "hybrid",
                "results": [{"chunk_id": "missing-required-fields"}],
                "elapsed_ms": 1.0,
                "fallback_reason": "",
            }
        )


def test_retrieval_failure_becomes_tool_failure() -> None:
    registry = _registry(StubRetrievalService(failure=OSError("index unavailable")))

    with pytest.raises(
        RuntimeError, match="Knowledge retrieval failed: index unavailable"
    ):
        registry.execute("search_knowledge_base", query="control")
