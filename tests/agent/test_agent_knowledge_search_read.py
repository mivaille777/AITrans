from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.agent_core.exceptions import AgentBudgetExceededError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.state import AgentState
from backend.agent_tools.knowledge import KnowledgeSearchResultData
from backend.models.agent_runtime import AgentCitationRef
from backend.rag.citation_service import CitationService
from backend.rag.config import RagRetrievalConfig, RagVectorStoreConfig
from backend.rag.embeddings.base import EmbeddingFingerprint
from backend.rag.exceptions import RagInvariantError
from backend.rag.index_manifest import IndexManifest, IndexManifestRecord, IndexStatus
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse.store import BM25SparseRetriever
from backend.rag.stores import FaissVectorStore
from backend.services.agent_tool_registry import AgentToolRegistry


def _chunk(
    index: int,
    *,
    document_id: str = "doc-A",
    section_path: tuple[str, ...] = ("Methods", "Training"),
    text: str | None = None,
) -> DocumentChunk:
    body = text or f"Full evidence text for chunk {index}."
    return DocumentChunk(
        chunk_id=f"chunk-{index}",
        document_id=document_id,
        text=body,
        title=f"Paper {document_id}",
        section_heading=section_path[-1] if section_path else "",
        section_path=list(section_path),
        page_number=index + 1,
        chunk_index=index,
        start_char=0,
        end_char=len(body),
        source_uri=f"file:///{document_id}.pdf",
    )


class _ChunkStore:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = {item.chunk_id: item for item in chunks}

    def get_chunk(self, chunk_id: str) -> DocumentChunk | None:
        return self.chunks.get(chunk_id)

    def section_neighbors(
        self,
        anchor: DocumentChunk,
        radius: int,
    ) -> list[DocumentChunk]:
        selected_section = tuple(anchor.section_path)
        same_section = sorted(
            (
                chunk
                for chunk in self.chunks.values()
                if chunk.document_id == anchor.document_id
                and tuple(chunk.section_path) == selected_section
            ),
            key=lambda item: (item.chunk_index, item.chunk_id),
        )
        anchor_index = next(
            index
            for index, item in enumerate(same_section)
            if item.chunk_id == anchor.chunk_id
        )
        return same_section[
            max(0, anchor_index - radius) : anchor_index + radius + 1
        ]


class _Retrieval:
    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, object]] = []

    def retrieve(self, query: str, *, filters=None) -> RetrievalResult:
        self.calls.append((query, filters))
        candidates = list(self.candidates)
        if filters and filters.document_ids:
            candidates = [
                item for item in candidates
                if item.chunk.document_id in filters.document_ids
            ]
        return RetrievalResult(
            query=query,
            candidates=candidates,
            retrieval_strategy="hybrid",
            elapsed_ms=1.0,
        )


def _registry(chunks: list[DocumentChunk], candidates=None) -> AgentToolRegistry:
    if candidates is None:
        candidates = [
            RetrievalCandidate(chunk=chunk, rank=index)
            for index, chunk in enumerate(chunks, start=1)
        ]
    return AgentToolRegistry(
        translation_service=SimpleNamespace(),
        quick_action_service=SimpleNamespace(),
        research_note_service=SimpleNamespace(),
        retrieval_service=_Retrieval(candidates),
        chunk_store=_ChunkStore(chunks),
        jit_search_read_enabled=True,
    )


def test_search_returns_only_bounded_snippets_and_never_evidence() -> None:
    long_chunk = _chunk(5, text=("A long body with  multiple\n spaces. " * 160))
    registry = _registry([long_chunk])

    result = registry.execute(
        "search_knowledge_base",
        query="training method",
        knowledge_document_ids=["doc-A"],
    )

    assert result.data is not None
    data = KnowledgeSearchResultData.model_validate(result.data)
    assert len(data.results) == 1
    assert len(data.results[0].snippet) <= 320
    assert "  " not in data.results[0].snippet
    assert "text" not in result.data["results"][0]
    assert data.evidence == []
    assert data.citations == []


def test_read_chunk_is_the_only_source_of_knowledge_evidence() -> None:
    chunks = [_chunk(4), _chunk(5)]
    registry = _registry(chunks)
    search = registry.execute(
        "search_knowledge_base",
        query="training method",
        knowledge_document_ids=["doc-A"],
    )
    assert search.data is not None
    assert search.data["evidence"] == []

    read = registry.execute(
        "read_knowledge_chunk",
        chunk_id="chunk-4",
        knowledge_document_ids=["doc-A"],
    )

    assert read.data is not None
    assert [item["evidence_id"] for item in read.data["evidence"]] == [
        "evidence:chunk-4"
    ]
    assert read.data["citations"][0]["evidence_ids"] == ["evidence:chunk-4"]
    assert [item["chunk_id"] for item in read.data["chunks"]] == ["chunk-4"]
    assert "Full evidence text for chunk 4." in read.output_text


def test_read_section_returns_bounded_same_section_neighbors() -> None:
    chunks = [_chunk(index) for index in range(3, 8)]
    chunks.append(
        _chunk(6, document_id="doc-A", section_path=("Results",)).model_copy(
            update={"chunk_id": "results-6"}
        )
    )
    registry = _registry(chunks)

    result = registry.execute(
        "read_knowledge_section",
        chunk_id="chunk-5",
        neighbor_radius=1,
        knowledge_document_ids=["doc-A"],
    )

    assert result.data is not None
    read_chunks = result.data["chunks"]
    assert [item["chunk_index"] for item in read_chunks] == [4, 5, 6]
    assert {tuple(item["section_path"]) for item in read_chunks} == {
        ("Methods", "Training")
    }
    assert len(result.data["evidence"]) == 3


def test_read_denies_chunks_outside_restricted_scope_before_returning_text() -> None:
    secret = _chunk(1, document_id="doc-B", text="private document body")
    registry = _registry([secret])

    with pytest.raises(PermissionError, match="outside the allowed document scope"):
        registry.execute(
            "read_knowledge_chunk",
            chunk_id="chunk-1",
            knowledge_document_ids=["doc-A"],
        )


def test_read_without_document_scope_requires_explicit_global_access() -> None:
    registry = _registry([_chunk(1)])

    with pytest.raises(PermissionError, match="explicit document scope"):
        registry.execute("read_knowledge_chunk", chunk_id="chunk-1")

    allowed = registry.execute(
        "read_knowledge_chunk",
        chunk_id="chunk-1",
        knowledge_scope_allow_global=True,
    )
    assert allowed.data is not None
    assert allowed.data["chunks"][0]["text"] == "Full evidence text for chunk 1."


@pytest.mark.parametrize("document_ids", [[], ["doc-A"]])
def test_jit_read_validation_preserves_scope_with_global_access(document_ids) -> None:
    chunk = _chunk(1)
    retrieval = _Retrieval([RetrievalCandidate(chunk=chunk, rank=1)])
    validated = []
    retrieval.validate_evidence_candidates = lambda result, *, filters: validated.append(filters)
    registry = AgentToolRegistry(
        translation_service=SimpleNamespace(),
        quick_action_service=SimpleNamespace(),
        research_note_service=SimpleNamespace(),
        retrieval_service=retrieval,
        chunk_store=_ChunkStore([chunk]),
        jit_search_read_enabled=True,
    )

    result = registry.execute(
        "read_knowledge_chunk", chunk_id="chunk-1",
        knowledge_document_ids=document_ids, knowledge_scope_allow_global=True,
    )

    assert result.data["evidence"]
    assert validated[0].document_ids == document_ids


def test_repeated_read_deduplicates_evidence_in_agent_state() -> None:
    registry = _registry([_chunk(1)])
    state = AgentState()
    first = registry.execute(
        "read_knowledge_chunk",
        chunk_id="chunk-1",
        knowledge_document_ids=["doc-A"],
    )
    first_result = asdict(first)
    state.record_tool_result(first_result)

    second = registry.execute(
        "read_knowledge_chunk",
        chunk_id="chunk-1",
        knowledge_document_ids=["doc-A"],
    )
    second_result = ProductAgentRuntimeAdapter._dedupe_read_result(
        state,
        "read_knowledge_chunk",
        asdict(second),
    )
    state.record_tool_result(second_result)

    assert second_result["data"]["duplicate_read"] is True
    assert second_result["data"]["duplicate_evidence_count"] == 1
    assert second_result["data"]["evidence"] == []
    all_ids = [
        raw["evidence_id"]
        for result in state.tool_results
        for raw in result["data"]["evidence"]
    ]
    assert all_ids == ["evidence:chunk-1"]


def test_search_snippet_cannot_become_a_valid_citation() -> None:
    registry = _registry([_chunk(1)])
    search = registry.execute(
        "search_knowledge_base",
        query="training",
        knowledge_document_ids=["doc-A"],
    )
    assert search.data is not None
    snippet_only = [
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence:chunk-1"],
            label="[1]",
        )
    ]

    with pytest.raises(RagInvariantError, match="unknown evidence_id"):
        CitationService().validate(snippet_only, search.data["evidence"])


def test_search_and_read_have_independent_budgets_and_block_overflow() -> None:
    control = AgentRunControl(
        policy=AgentExecutionPolicy(max_tool_calls=10, max_knowledge_reads=2)
    )
    control.claim_knowledge_action("search_knowledge_base")
    control.claim_knowledge_action("read_knowledge_chunk")
    control.claim_knowledge_action("read_knowledge_section")

    with pytest.raises(AgentBudgetExceededError, match="read budget is exhausted"):
        control.claim_knowledge_action("read_knowledge_chunk")

    assert control.knowledge_search_count == 1
    assert control.knowledge_read_count == 2


@pytest.mark.parametrize("top_k", [None, 1])
def test_search_no_hits_returns_empty_results_without_evidence(top_k: int | None) -> None:
    registry = _registry([], candidates=[])
    result = registry.execute(
        "search_knowledge_base", query="missing information",
        knowledge_document_ids=["doc-A"], top_k=top_k,
    )
    assert result.data is not None
    data = KnowledgeSearchResultData.model_validate(result.data)
    assert data.results == []
    assert data.evidence == []
    assert data.citations == []


def test_agent_search_cache_reuses_vectors_without_reusing_stale_or_private_evidence(
    tmp_path: Path,
) -> None:
    embedding = SimpleNamespace(
        model_name="cache-test", dimension=2,
        fingerprint=EmbeddingFingerprint(
            model_id="cache-test", dimension=2, normalized=True,
            query_prefix="query", document_prefix="", model_revision="v1",
        ),
        embed_query=Mock(return_value=[1.0, 0.0]),
    )
    manifest = IndexManifest(tmp_path / "manifest.json")
    vector = FaissVectorStore(
        RagVectorStoreConfig(storage_path=str(tmp_path / "faiss")), dimension=2,
        fingerprint=embedding.fingerprint.as_dict(),
    )
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    retrieval = RetrievalService(
        embedding_provider=embedding, vector_store=vector, sparse_retriever=sparse,
        manifest=manifest, config=RagRetrievalConfig(embedding_cache_size=8),
    )
    registry = AgentToolRegistry(
        translation_service=SimpleNamespace(), quick_action_service=SimpleNamespace(),
        research_note_service=SimpleNamespace(), retrieval_service=retrieval,
        chunk_store=sparse, jit_search_read_enabled=True,
    )

    def publish(chunk: DocumentChunk, generation: str, *, neighbors=()) -> None:
        chunks = [chunk, *neighbors]
        ids = [item.chunk_id for item in chunks]
        manifest.begin_generation(chunk.document_id, generation, ids)
        vector.upsert_chunks(chunks, [[1.0, 0.0] for _ in chunks], generation_id=generation)
        sparse.index_chunks(chunks, generation_id=generation)
        manifest.validate_generation(chunk.document_id, generation, ids)
        manifest.publish_generation(
            chunk.document_id, generation,
            manifest_record=IndexManifestRecord(
                document_id=chunk.document_id, chunk_ids=ids, generation_id=generation,
                embedding_fingerprint=embedding.fingerprint.as_dict(), status=IndexStatus.READY,
            ),
        )

    def search(document_id: str) -> KnowledgeSearchResultData:
        result = registry.execute(
            "search_knowledge_base", query="training", knowledge_document_ids=[document_id],
        )
        assert result.data is not None
        return KnowledgeSearchResultData.model_validate(result.data)

    try:
        publish(_chunk(1), "a-v1")
        publish(_chunk(3, document_id="doc-B"), "b-v1")
        assert [item.chunk_id for item in search("doc-A").results] == ["chunk-1"]
        read = registry.execute(
            "read_knowledge_chunk", chunk_id="chunk-1", knowledge_document_ids=["doc-A"],
        )
        assert [item["chunk_id"] for item in read.data["chunks"]] == ["chunk-1"]
        section = registry.execute(
            "read_knowledge_section", chunk_id="chunk-1", knowledge_document_ids=["doc-A"],
            neighbor_radius=1,
        )
        assert [item["chunk_id"] for item in section.data["chunks"]] == ["chunk-1"]
        assert [item.chunk_id for item in search("doc-A").results] == ["chunk-1"]
        assert embedding.embed_query.call_count == 1
        assert [item.chunk_id for item in search("doc-B").results] == ["chunk-3"]
        assert embedding.embed_query.call_count == 2

        publish(_chunk(2), "a-v2")
        assert [item.chunk_id for item in search("doc-A").results] == ["chunk-2"]
        with pytest.raises(LookupError, match="no longer exists"):
            registry.execute(
                "read_knowledge_chunk", chunk_id="chunk-1", knowledge_document_ids=["doc-A"],
            )
        current_read = registry.execute(
            "read_knowledge_chunk", chunk_id="chunk-2", knowledge_document_ids=["doc-A"],
        )
        assert [item["chunk_id"] for item in current_read.data["chunks"]] == ["chunk-2"]
        assert embedding.embed_query.call_count == 3
        assert [item.chunk_id for item in search("doc-A").results] == ["chunk-2"]
        assert embedding.embed_query.call_count == 3

        embedding.fingerprint = EmbeddingFingerprint(
            model_id="cache-test", dimension=2, normalized=True,
            query_prefix="query", document_prefix="", model_revision="v2",
        )
        changed_model = search("doc-A")
        assert embedding.embed_query.call_count == 4
        assert changed_model.retrieval_strategy == "sparse-only"
        assert [item.chunk_id for item in changed_model.results] == ["chunk-2"]
        assert "reindex required" in changed_model.fallback_reason

        publish(_chunk(2), "a-v3", neighbors=(_chunk(3),))
        rebuilt_section = registry.execute(
            "read_knowledge_section", chunk_id="chunk-2", knowledge_document_ids=["doc-A"],
            neighbor_radius=1,
        )
        assert [item["chunk_id"] for item in rebuilt_section.data["chunks"]] == ["chunk-2", "chunk-3"]
        assert {item["metadata"]["index_generation"] for item in rebuilt_section.data["evidence"]} == {"a-v3"}

        manifest.delete("doc-A")
        vector.delete_document("doc-A")
        sparse.delete_document("doc-A")
        assert search("doc-A").results == []
        with pytest.raises(LookupError, match="no longer exists"):
            registry.execute(
                "read_knowledge_section", chunk_id="chunk-2", knowledge_document_ids=["doc-A"],
            )
        assert search("unknown-document").results == []
    finally:
        vector.close()
