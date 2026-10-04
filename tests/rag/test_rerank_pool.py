from types import SimpleNamespace

import pytest

from backend.rag.config import RagRetrievalConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.retrieval_service import RetrievalService


@pytest.mark.parametrize("pool", [8, 12, 20])
def test_pool_admits_lower_ranked_candidates_before_final_truncation(pool):
    candidates = [
        RetrievalCandidate(
            chunk=DocumentChunk(
                chunk_id=f"c{i}", document_id="doc", chunk_index=i-1, text=f"text {i}",
            ),
            rank=i, sparse_score=float(21-i),
        )
        for i in range(1, 21)
    ]
    calls = []

    def rerank(query, items, *, top_k):
        calls.append([item.chunk.chunk_id for item in items])
        return list(reversed(items))[:top_k]

    service = RetrievalService(
        embedding_provider=SimpleNamespace(), vector_store=SimpleNamespace(),
        sparse_retriever=SimpleNamespace(search=lambda *args, **kwargs: candidates),
        reranker=SimpleNamespace(rerank=rerank),
        config=RagRetrievalConfig(rerank_candidate_k=pool, small_to_big_enabled=False),
    )
    result = service.retrieve("query", dense_enabled=False, structural_enabled=False)
    assert calls == [[f"c{i}" for i in range(1, pool+1)]]
    assert len(result.candidates) == 8
    assert result.candidates[0].chunk.chunk_id == f"c{pool}"
    assert len(result.metadata["post_rerank_chunk_ids"]) == pool
    from datetime import datetime
    spans = result.metadata["stage_timings"]
    assert set(spans) == {"sparse", "fusion", "rerank"}
    root = result.metadata["retrieval_span"]
    for span in spans.values():
        assert span["parent_id"] == root["span_id"]
        start = datetime.fromisoformat(span["started_at"])
        end = datetime.fromisoformat(span["ended_at"])
        assert start.tzinfo and end >= start
        assert span["elapsed_ms"] == pytest.approx((end - start).total_seconds() * 1000, abs=0.002)
