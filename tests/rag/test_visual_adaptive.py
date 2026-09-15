from __future__ import annotations

from types import SimpleNamespace

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import DocumentChunk
from backend.rag.visual_adaptive import (
    AdaptivePrefetchPolicy,
    AdaptiveQdrantTwoStageVisualStore,
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


class _FakeClient:
    def __init__(self, *, candidate_count: int = 200) -> None:
        self.candidate_count = candidate_count
        self.query_calls = []

    def count(self, **kwargs):
        return SimpleNamespace(count=self.candidate_count)

    def query_points(self, **kwargs):
        self.query_calls.append(kwargs)
        payload = _chunk("visual-a").model_dump(mode="json")
        payload["source_kind"] = "pdf"
        payload["visual_index_version"] = "v"
        return SimpleNamespace(
            points=[SimpleNamespace(payload=payload, score=0.9)]
        )


class _Store(AdaptiveQdrantTwoStageVisualStore):
    def ensure_collection(self) -> None:
        return None


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


def test_adaptive_store_uses_filtered_candidate_count_for_prefetch() -> None:
    client = _FakeClient(candidate_count=200)
    store = _Store(
        _config(),
        client=client,  # type: ignore[arg-type]
        policy=AdaptivePrefetchPolicy(
            enabled=True,
            min_k=24,
            max_k=96,
            candidate_ratio=0.25,
        ),
    )

    results = store.search([[1.0, 0.0], [0.0, 1.0]], top_k=2)

    assert client.query_calls[0]["prefetch"].limit == 50
    assert results[0].metadata["visual_prefetch_k"] == 50
    assert results[0].metadata["visual_candidate_count"] == 200
    assert results[0].metadata["visual_prefetch_adaptive"] is True
    assert results[0].metadata["visual_maxsim_candidate_reduction"] == 0.75


def test_fixed_prefetch_store_disables_adaptive_sizing() -> None:
    client = _FakeClient(candidate_count=200)
    store = _Store(
        _config(),
        client=client,  # type: ignore[arg-type]
        policy=AdaptivePrefetchPolicy(enabled=True),
    )
    fixed = store.fixed_prefetch_store(24)
    fixed.ensure_collection = lambda: None  # type: ignore[method-assign]

    results = fixed.search([[1.0, 0.0]], top_k=2)

    assert client.query_calls[-1]["prefetch"].limit == 24
    assert results[0].metadata["visual_prefetch_adaptive"] is False
    assert results[0].metadata["visual_prefetch_k"] == 24
