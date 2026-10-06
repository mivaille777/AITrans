from __future__ import annotations


from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import DocumentChunk
from backend.rag.visual_adaptive import (
    AdaptivePrefetchPolicy,
    adaptive_prefetch_top_k,
)


def _config(**updates) -> RagVisualRetrievalConfig:
    values = {
        "enabled": True,
        "dimension": 2,
        "visual_top_k": 2,
        "prefetch_top_k": 48,
        "prefetch_fallback_to_full_scan": True,
    }
    values.update(updates)
    return RagVisualRetrievalConfig(**values)


def _chunk(chunk_id: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=f"visual {chunk_id}",
        title="Paper",
        page_number=1,
        chunk_index=0,
        token_count=2,
        source_uri="file:///paper.pdf",
        document_hash="hash",
        parser_version="parser",
        chunker_version="chunker",
        embedding_version="visual",
        metadata={"source_kind": "pdf"},
    )


def test_adaptive_prefetch_scales_and_caps_candidate_pool() -> None:
    policy = AdaptivePrefetchPolicy(
        enabled=True,
        min_k=24,
        max_k=96,
        candidate_ratio=0.25,
    )
    assert adaptive_prefetch_top_k(
        candidate_count=40,
        visual_top_k=12,
        fallback_prefetch_k=48,
        policy=policy,
    ) == 24
    assert adaptive_prefetch_top_k(
        candidate_count=200,
        visual_top_k=12,
        fallback_prefetch_k=48,
        policy=policy,
    ) == 50
    assert adaptive_prefetch_top_k(
        candidate_count=1000,
        visual_top_k=12,
        fallback_prefetch_k=48,
        policy=policy,
    ) == 96
    assert adaptive_prefetch_top_k(
        candidate_count=10,
        visual_top_k=12,
        fallback_prefetch_k=48,
        policy=policy,
    ) == 10


def test_adaptive_prefetch_falls_back_when_count_is_unavailable() -> None:
    policy = AdaptivePrefetchPolicy(enabled=True)
    assert adaptive_prefetch_top_k(
        candidate_count=None,
        visual_top_k=12,
        fallback_prefetch_k=48,
        policy=policy,
    ) == 48
