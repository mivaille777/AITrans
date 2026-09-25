from __future__ import annotations

import pytest

from backend.rag.config import RagRetrievalConfig
from backend.rag.exceptions import RagRetrievalError
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.base import VectorSearchFilter


def item(
    chunk_id: str,
    *,
    dense=False,
    sparse=False,
    rank=1,
    document_id="doc",
    section="",
    page=None,
    chunk_index=0,
):
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            text=chunk_id,
            section_heading=section,
            page_number=page,
            chunk_index=chunk_index,
        ),
        dense_score=0.8 if dense else None,
        sparse_score=3.0 if sparse else None,
        rank=rank,
    )


class Embedding:
    model_name = "fake"
    dimension = 2

    def __init__(self, fail=False):
        self.fail = fail

    def embed_query(self, _text):
        if self.fail:
            raise RuntimeError("dense failed")
        return [1.0, 0.0]

    def embed_documents(self, _texts):
        return []


class VectorStore:
    def __init__(self, results=None, fail=False):
        self.results = results or []
        self.fail = fail
        self.filters = None

    def search(self, _vector, *, top_k, filters=None):
        self.filters = filters
        if self.fail:
            raise RuntimeError("dense failed")
        return self.results[:top_k]


class Sparse:
    def __init__(self, results=None, fail=False, section_results=None):
        self.results = results or []
        self.fail = fail
        self.section_results = section_results or []
        self.filters = None
        self.section_calls = []

    def search(self, _query, top_k, filters=None):
        self.filters = filters
        if self.fail:
            raise RuntimeError("sparse failed")
        return self.results[:top_k]

    def search_sections(self, headings, top_k, filters=None):
        self.section_calls.append((headings, top_k, filters))
        return self.section_results[:top_k]


def service(
    *,
    dense=None,
    sparse=None,
    structural=None,
    dense_fail=False,
    sparse_fail=False,
    config=None,
    reranker=None,
):
    vector_store = VectorStore(dense, dense_fail)
    sparse_store = Sparse(sparse, sparse_fail, structural)
    return (
        RetrievalService(
            embedding_provider=Embedding(),
            vector_store=vector_store,
            sparse_retriever=sparse_store,
            config=config
            or RagRetrievalConfig(
                dense_top_k=30,
                sparse_top_k=30,
                fusion_top_k=20,
                final_top_k=8,
            ),
            reranker=reranker,
        ),
        vector_store,
        sparse_store,
    )


def test_hybrid_retrieval_fuses_and_deduplicates() -> None:
    retrieval, *_ = service(
        dense=[item("shared", dense=True), item("dense", dense=True, rank=2)],
        sparse=[item("shared", sparse=True), item("sparse", sparse=True, rank=2)],
    )

    result = retrieval.retrieve("query")

    assert result.retrieval_strategy == "hybrid"
    assert [candidate.chunk.chunk_id for candidate in result.candidates] == [
        "shared",
        "dense",
        "sparse",
    ]
    assert result.metadata["fusion_count"] == 3
    assert result.metadata["fusion_candidate_count"] == 3
    assert result.metadata["rerank_candidate_count"] == 0
    assert result.metadata["final_candidate_count"] == 3
    assert result.metadata["pre_rerank_chunk_ids"] == ["shared", "dense", "sparse"]
    assert result.metadata["dense_chunk_ids"] == ["shared", "dense"]
    assert result.metadata["sparse_chunk_ids"] == ["shared", "sparse"]


def test_filters_are_pushed_to_both_stores() -> None:
    retrieval, vector, sparse = service()
    filters = VectorSearchFilter(document_ids=["doc"], language="en")

    retrieval.retrieve("query", filters=filters)

    assert vector.filters is filters
    assert sparse.filters is filters


def test_retrieval_channels_can_be_disabled_for_ablation_profiles() -> None:
    dense_retrieval, dense_vector, dense_sparse = service(
        dense=[item("dense", dense=True)],
        sparse=[item("sparse", sparse=True)],
    )
    dense_result = dense_retrieval.retrieve(
        "query",
        dense_enabled=True,
        sparse_enabled=False,
        reranker_enabled=False,
        small_to_big_enabled=False,
    )
    assert dense_result.retrieval_strategy == "dense-only"
    assert [candidate.chunk.chunk_id for candidate in dense_result.candidates] == ["dense"]
    assert dense_vector.filters is not None
    assert dense_sparse.filters is None

    sparse_retrieval, sparse_vector, sparse_store = service(
        dense=[item("dense", dense=True)],
        sparse=[item("sparse", sparse=True)],
    )
    sparse_result = sparse_retrieval.retrieve(
        "query",
        dense_enabled=False,
        sparse_enabled=True,
        reranker_enabled=False,
        small_to_big_enabled=False,
    )
    assert sparse_result.retrieval_strategy == "sparse-only"
    assert [candidate.chunk.chunk_id for candidate in sparse_result.candidates] == ["sparse"]
    assert sparse_vector.filters is None
    assert sparse_store.filters is not None


def test_structural_retrieval_can_be_disabled_even_when_hints_are_present() -> None:
    retrieval, _vector, sparse_store = service(
        dense=[item("dense", dense=True)],
        sparse=[item("sparse", sparse=True)],
        structural=[item("structure", sparse=True, section="References")],
    )

    result = retrieval.retrieve(
        "references",
        section_hints=("references",),
        structural_enabled=False,
    )

    assert result.metadata["structural_enabled"] is False
    assert result.metadata["structural_count"] == 0
    assert sparse_store.section_calls == []


def test_structural_section_recall_is_fused_and_promoted_before_body_chunks() -> None:
    references = item(
        "ref-1",
        sparse=True,
        section="6. References",
        page=11,
        chunk_index=8,
    )
    body = item(
        "body",
        dense=True,
        section="4. Results",
        page=8,
        chunk_index=5,
    )
    retrieval, _vector, sparse_store = service(
        dense=[body],
        sparse=[body],
        structural=[references],
    )

    result = retrieval.retrieve(
        "paper references",
        section_hints=("references", "bibliography"),
        final_top_k=12,
    )

    assert result.retrieval_strategy == "hybrid+structural"
    assert [candidate.chunk.chunk_id for candidate in result.candidates] == [
        "ref-1",
        "body",
    ]
    assert result.metadata["structural_count"] == 1
    assert result.metadata["structural_section_hints"] == [
        "references",
        "bibliography",
    ]
    assert sparse_store.section_calls[0][0] == ("references", "bibliography")


def test_dense_failure_degrades_to_sparse_only() -> None:
    retrieval, *_ = service(
        sparse=[item("sparse", sparse=True)],
        dense_fail=True,
    )

    result = retrieval.retrieve("query")

    assert result.retrieval_strategy == "sparse-only"
    assert result.candidates[0].chunk.chunk_id == "sparse"
    assert result.metadata["fallback_reason"] == "dense failed"


def test_sparse_failure_degrades_to_dense_only() -> None:
    retrieval, *_ = service(
        dense=[item("dense", dense=True)],
        sparse_fail=True,
    )

    result = retrieval.retrieve("query")

    assert result.retrieval_strategy == "dense-only"
    assert result.candidates[0].chunk.chunk_id == "dense"


def test_both_fail_raise_explicit_retrieval_error() -> None:
    retrieval, *_ = service(dense_fail=True, sparse_fail=True)

    with pytest.raises(RagRetrievalError, match="dense and sparse"):
        retrieval.retrieve("query")


def test_structural_recall_can_survive_dense_and_sparse_failure() -> None:
    references = item("ref", sparse=True, section="References", page=10)
    retrieval, *_ = service(
        structural=[references],
        dense_fail=True,
        sparse_fail=True,
    )

    result = retrieval.retrieve(
        "references",
        section_hints=("references",),
    )

    assert result.retrieval_strategy == "structural-only"
    assert result.candidates[0].chunk.chunk_id == "ref"


def test_latency_and_count_metadata_are_present() -> None:
    retrieval, *_ = service(
        dense=[item("dense", dense=True)],
        sparse=[item("sparse", sparse=True)],
    )

    result = retrieval.retrieve("query")

    assert result.elapsed_ms >= 0
    assert result.metadata["dense_count"] == 1
    assert result.metadata["sparse_count"] == 1
    assert result.metadata["structural_count"] == 0
    assert result.metadata["dense_search_ms"] >= 0
    assert result.metadata["sparse_search_ms"] >= 0
    assert result.metadata["structural_search_ms"] >= 0
    assert result.metadata["fusion_ms"] >= 0
    assert result.metadata["embedding_ms"] >= 0
    assert result.metadata["rerank_ms"] >= 0
    assert result.metadata["final_count"] == 2
    assert result.metadata["fusion_candidate_count"] == 2
    assert result.metadata["final_candidate_count"] == 2


def test_rerank_pool_can_rescue_candidate_below_final_top_k() -> None:
    class RescueReranker:
        def rerank(self, _query, candidates, *, top_k):
            ordered = list(candidates)
            gold = next(
                candidate
                for candidate in ordered
                if candidate.chunk.chunk_id == "gold"
            )
            return [gold, *[item for item in ordered if item is not gold]][:top_k]

    dense = [
        item(
            "gold" if rank == 12 else f"chunk-{rank:02d}",
            dense=True,
            rank=rank,
        )
        for rank in range(1, 21)
    ]
    retrieval, *_ = service(
        dense=dense,
        config=RagRetrievalConfig(
            dense_top_k=30,
            sparse_top_k=30,
            fusion_top_k=20,
            rerank_candidate_k=20,
            final_top_k=8,
        ),
        reranker=RescueReranker(),
    )

    result = retrieval.retrieve("query", sparse_enabled=False)

    assert result.candidates[0].chunk.chunk_id == "gold"
    assert "gold" in result.metadata["rerank_input_chunk_ids"]
    assert result.metadata["fusion_candidate_count"] == 20
    assert result.metadata["rerank_candidate_count"] == 20
    assert result.metadata["final_candidate_count"] == 8


def test_rerank_candidate_pool_size_is_independent_of_final_top_k() -> None:
    class RecordingReranker:
        def __init__(self):
            self.received = []

        def rerank(self, _query, candidates, *, top_k):
            self.received = list(candidates)
            return list(candidates)[:top_k]

    recorder = RecordingReranker()
    dense = [
        item(f"chunk-{rank:02d}", dense=True, rank=rank)
        for rank in range(1, 21)
    ]
    retrieval, *_ = service(
        dense=dense,
        config=RagRetrievalConfig(
            fusion_top_k=20,
            rerank_candidate_k=12,
            final_top_k=8,
        ),
        reranker=recorder,
    )

    result = retrieval.retrieve("query", sparse_enabled=False)

    assert len(recorder.received) == 12
    assert len(result.candidates) == 8
    assert result.metadata["rerank_candidate_count"] == 12
    assert len(result.metadata["post_rerank_chunk_ids"]) == 12


def test_reranker_is_applied_and_failure_falls_back_to_rrf() -> None:
    class Reranker:
        def __init__(self, fail=False):
            self.fail = fail

        def rerank(self, _query, candidates, *, top_k):
            if self.fail:
                raise RuntimeError("rerank failed")
            return list(reversed(candidates))[:top_k]

    dense = [item("first", dense=True), item("second", dense=True, rank=2)]
    retrieval, *_ = service(dense=dense, reranker=Reranker())
    applied = retrieval.retrieve("query")
    assert applied.metadata["reranker_applied"] is True
    assert applied.candidates[0].chunk.chunk_id == "second"

    retrieval._reranker = Reranker(fail=True)
    fallback = retrieval.retrieve("query")
    assert fallback.metadata["reranker_applied"] is False
    assert fallback.metadata["reranker_fallback_reason"] == "rerank failed"



def test_reranker_failure_restores_full_rrf_order() -> None:
    class FailingReranker:
        def rerank(self, _query, candidates, *, top_k):
            raise RuntimeError("reranker unavailable")

    dense = [
        item(f"chunk-{rank:02d}", dense=True, rank=rank)
        for rank in range(1, 13)
    ]
    retrieval, *_ = service(
        dense=dense,
        config=RagRetrievalConfig(
            fusion_top_k=12,
            rerank_candidate_k=10,
            final_top_k=8,
        ),
        reranker=FailingReranker(),
    )

    result = retrieval.retrieve("query", sparse_enabled=False)

    assert [item.chunk.chunk_id for item in result.candidates] == [
        f"chunk-{rank:02d}" for rank in range(1, 9)
    ]
    assert result.metadata["reranker_applied"] is False
    assert result.metadata["reranker_fallback_reason"] == "reranker unavailable"
    assert result.metadata["post_rerank_chunk_ids"] == [
        f"chunk-{rank:02d}" for rank in range(1, 13)
    ]


def test_section_hints_rerank_full_fused_pool_without_duplicates() -> None:
    class ReverseReranker:
        def __init__(self):
            self.received_ids = []

        def rerank(self, _query, candidates, *, top_k):
            self.received_ids = [item.chunk.chunk_id for item in candidates]
            return list(reversed(candidates))[:top_k]

    reranker = ReverseReranker()
    body = [
        item(f"body-{rank}", dense=True, rank=rank, section="Results")
        for rank in range(1, 6)
    ]
    structural = [
        item("ref-1", sparse=True, section="References", chunk_index=20),
        item("ref-2", sparse=True, section="Bibliography", chunk_index=21),
    ]
    retrieval, *_ = service(
        dense=body,
        structural=structural,
        config=RagRetrievalConfig(
            fusion_top_k=20,
            rerank_candidate_k=8,
            final_top_k=8,
        ),
        reranker=reranker,
    )

    result = retrieval.retrieve(
        "references",
        section_hints=("references", "bibliography"),
        sparse_enabled=False,
    )

    assert len(reranker.received_ids) == result.metadata["fusion_candidate_count"]
    assert len(reranker.received_ids) == len(set(reranker.received_ids))
    assert [item.rank for item in result.candidates] == list(
        range(1, len(result.candidates) + 1)
    )
    assert len({item.chunk.chunk_id for item in result.candidates}) == len(
        result.candidates
    )
