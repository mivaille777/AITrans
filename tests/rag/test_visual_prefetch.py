from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from qdrant_client.http import models as qdrant_models

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.models import DocumentChunk
from backend.rag.visual_prefetch import (
    COARSE_VECTOR_NAME,
    LATE_VECTOR_NAME,
    QdrantTwoStageVisualStore,
    create_visual_vector_store,
    pool_multivector,
)
from backend.rag.visual_retrieval import QdrantVisualMultiVectorStore


def _config(**updates) -> RagVisualRetrievalConfig:
    values = {
        "enabled": True,
        "dimension": 2,
        "visual_top_k": 2,
        "prefetch_top_k": 6,
    }
    values.update(updates)
    return RagVisualRetrievalConfig(**values)


def _chunk() -> DocumentChunk:
    return DocumentChunk(
        chunk_id="visual-page",
        document_id="doc-1",
        text="Native visual page from Paper.",
        title="Paper",
        page_number=1,
        chunk_index=0,
        token_count=8,
        source_uri="file:///paper.pdf",
        document_hash="hash-v1",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        embedding_version="native-visual-multivector",
        metadata={
            "source_kind": "pdf",
            "modality": "page",
            "native_visual_retrieval": True,
        },
    )


class FakeQdrantClient:
    def __init__(self, *, fail_prefetch: bool = False) -> None:
        self.fail_prefetch = fail_prefetch
        self.created: list[dict[str, object]] = []
        self.query_calls: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []

    def collection_exists(self, _collection_name: str) -> bool:
        return False

    def create_collection(self, **kwargs) -> None:
        self.created.append(kwargs)

    def scroll(self, **_kwargs):
        return [], None

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def delete(self, **_kwargs) -> None:
        return None

    def query_points(self, **kwargs):
        self.query_calls.append(kwargs)
        if self.fail_prefetch and kwargs.get("prefetch") is not None:
            raise RuntimeError("synthetic prefetch failure")
        payload = _chunk().model_dump(mode="json")
        payload["source_kind"] = "pdf"
        payload["visual_index_version"] = "test-version"
        payload["visual_search_schema"] = "visual-prefetch-v1"
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload=payload,
                    score=7.5,
                )
            ]
        )

    def close(self) -> None:
        return None


def test_visual_prefetch_config_requires_oversampling() -> None:
    with pytest.raises(ValueError, match="prefetch_top_k"):
        _config(visual_top_k=8, prefetch_top_k=4)


def test_pool_multivector_builds_normalized_centroid() -> None:
    pooled = pool_multivector([[1.0, 0.0], [0.0, 1.0]], 2)
    expected = 1.0 / math.sqrt(2.0)
    assert pooled == pytest.approx([expected, expected])


def test_two_stage_store_indexes_coarse_and_late_vectors() -> None:
    client = FakeQdrantClient()
    store = QdrantTwoStageVisualStore(_config(), client=client)

    store.replace_document(
        "doc-1",
        [_chunk()],
        [[[1.0, 0.0], [0.0, 1.0]]],
        index_version="test-version",
    )

    assert client.created
    vectors_config = client.created[0]["vectors_config"]
    assert isinstance(vectors_config, dict)
    assert set(vectors_config) == {COARSE_VECTOR_NAME, LATE_VECTOR_NAME}
    late = vectors_config[LATE_VECTOR_NAME]
    assert isinstance(late, qdrant_models.VectorParams)
    assert (
        late.multivector_config.comparator
        == qdrant_models.MultiVectorComparator.MAX_SIM
    )

    assert client.upserts
    point = client.upserts[0]["points"][0]
    assert set(point.vector) == {COARSE_VECTOR_NAME, LATE_VECTOR_NAME}
    assert point.vector[COARSE_VECTOR_NAME] == pytest.approx(
        [1.0 / math.sqrt(2.0), 1.0 / math.sqrt(2.0)]
    )
    assert point.vector[LATE_VECTOR_NAME] == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]


def test_two_stage_search_prefetches_then_runs_maxsim() -> None:
    client = FakeQdrantClient()
    store = QdrantTwoStageVisualStore(_config(prefetch_top_k=7), client=client)

    results = store.search(
        [[1.0, 0.0], [0.0, 1.0]],
        top_k=2,
    )

    assert len(client.query_calls) == 1
    call = client.query_calls[0]
    prefetch = call["prefetch"]
    assert isinstance(prefetch, qdrant_models.Prefetch)
    assert prefetch.using == COARSE_VECTOR_NAME
    assert prefetch.limit == 7
    assert call["using"] == LATE_VECTOR_NAME
    assert call["query"] == [[1.0, 0.0], [0.0, 1.0]]
    assert results[0].metadata["visual_search_mode"] == "coarse-prefetch-maxsim"
    assert results[0].metadata["visual_prefetch_limit"] == 7


def test_two_stage_search_falls_back_to_full_maxsim() -> None:
    client = FakeQdrantClient(fail_prefetch=True)
    store = QdrantTwoStageVisualStore(
        _config(prefetch_fallback_to_full_scan=True),
        client=client,
    )

    results = store.search(
        [[1.0, 0.0], [0.0, 1.0]],
        top_k=2,
    )

    assert len(client.query_calls) == 2
    assert client.query_calls[0]["prefetch"] is not None
    assert "prefetch" not in client.query_calls[1]
    assert client.query_calls[1]["using"] == LATE_VECTOR_NAME
    assert results[0].metadata["visual_search_mode"] == "full-maxsim-fallback"
    assert "synthetic prefetch failure" in results[0].metadata[
        "visual_prefetch_fallback_reason"
    ]


def test_factory_keeps_exact_stage3_store_when_prefetch_disabled() -> None:
    client = FakeQdrantClient()
    store = create_visual_vector_store(
        _config(prefetch_enabled=False, prefetch_top_k=1),
        client=client,
    )
    assert type(store) is QdrantVisualMultiVectorStore
