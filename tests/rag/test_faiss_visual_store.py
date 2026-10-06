import numpy as np
import pytest

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.exceptions import RagVectorStoreError
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.stores.faiss_visual import FaissVisualMultiVectorStore
from backend.rag.visual_retrieval import visual_retrieval_index_version
from tests.rag.test_visual_retrieval import _chunk


def make_store(tmp_path, **updates):
    config = RagVisualRetrievalConfig(
        enabled=True,
        dimension=2,
        storage_path=str(tmp_path),
        visual_top_k=2,
        prefetch_top_k=6,
        **updates,
    )
    return FaissVisualMultiVectorStore(config), visual_retrieval_index_version(config)


def populate(store, version, count=200):
    chunks = [_chunk(f"page-{i:04d}", document_id="doc-1") for i in range(count)]
    store.replace_document(
        "doc-1", chunks, [[[1.0, 0.0], [0.0, 1.0]]] * count, index_version=version
    )


def test_adaptive_and_fixed_prefetch_share_durable_tokens(tmp_path):
    store, version = make_store(tmp_path)
    try:
        populate(store, version)
        hits = store.search([[1.0, 0.0]], top_k=2)
        assert hits[0].metadata["visual_prefetch_k"] == 50
        assert hits[0].metadata["visual_candidate_count"] == 200
        assert hits[0].metadata["visual_maxsim_candidate_reduction"] == 0.75
        assert hits[0].metadata["visual_score"] == 1.0
        fixed = store.fixed_prefetch_store(24)
        assert fixed.repository is store.repository
        hits = fixed.search([[1.0, 0.0]], top_k=2)
        assert hits[0].metadata["visual_prefetch_k"] == 24
        assert hits[0].metadata["visual_prefetch_adaptive"] is False
        fixed.close()
        assert store.search([[1.0, 0.0]], top_k=2)
    finally:
        store.close()


def test_scope_generation_and_reopen(tmp_path):
    store, version = make_store(tmp_path)
    page = _chunk("a").model_copy(update={"metadata": {"index_generation": "g1"}})
    store.replace_document("doc-1", [page], [[[1.0, 0.0]]], index_version=version)
    page.metadata["index_generation"] = "g2"
    store.replace_document("doc-1", [page], [[[0.0, 1.0]]], index_version=version)
    assert len(store.list_chunks()) == 2
    assert store.search([[1.0, 0.0]], top_k=2) == []
    assert store.search([[1.0, 0.0]], top_k=2, active_generations={}) == []
    assert (
        store.search(
            [[1.0, 0.0]],
            top_k=2,
            filters=VectorSearchFilter(document_ids=["private"]),
            active_generations={"doc-1": "g1"},
        )
        == []
    )
    assert (
        store.search_full_maxsim(
            [[1.0, 0.0]], top_k=2, active_generations={"doc-1": "g1"}
        )[0].metadata["visual_score"]
        == 1.0
    )
    store.close()
    store, _ = make_store(tmp_path)
    assert (
        store.search([[1.0, 0.0]], top_k=2, active_generations={"doc-1": "g2"})[
            0
        ].metadata["visual_score"]
        == 0.0
    )
    store.delete_document("doc-1")
    assert store.search([[1.0, 0.0]], top_k=2, active_generations={"doc-1": "g1"}) == []
    store.close()


def test_prefetch_failure_has_exact_scoped_fallback(tmp_path, monkeypatch):
    store, version = make_store(tmp_path)
    try:
        populate(store, version, 5)

        def fail(*args):
            raise RuntimeError("synthetic prefetch failure")

        monkeypatch.setattr(store, "_coarse_candidates", fail)
        hits = store.search([[1.0, 0.0]], top_k=2)
        assert hits[0].metadata["visual_search_mode"] == "full-maxsim-fallback"
        assert hits[0].metadata["visual_maxsim_candidate_reduction"] == 0.0
        assert "synthetic" in hits[0].metadata["visual_prefetch_fallback_reason"]
        store._config.prefetch_fallback_to_full_scan = False
        with pytest.raises(RagVectorStoreError):
            store.search([[1.0, 0.0]], top_k=2)
    finally:
        store.close()


def test_invalid_batch_preserves_existing_document(tmp_path):
    store, version = make_store(tmp_path)
    try:
        populate(store, version, 1)
        before = store.list_chunks()
        with pytest.raises(RagVectorStoreError):
            store.replace_document(
                "doc-1",
                [_chunk("a"), _chunk("b")],
                [[[1.0, 0.0]], [[float("nan"), 0.0]]],
                index_version=version,
            )
        assert store.list_chunks() == before
        rows = store.repository.rows(
            store.collection_name, with_vectors=True, with_coarse=True
        )
        assert rows[0].vector.shape == (2, 2)
        assert rows[0].coarse == pytest.approx([1 / np.sqrt(2)] * 2)
    finally:
        store.close()


def test_replacement_preserves_ids_and_removes_only_stale_current_rows(tmp_path):
    store, version = make_store(tmp_path)
    try:
        populate(store, version, 3)
        original = {
            r.chunk.chunk_id: r.vector_id
            for r in store.repository.rows(store.collection_name)
        }
        chunks = store.list_chunks()[:2]
        store.replace_document(
            "doc-1", chunks, [[[2.0, 0.0]]] * 2, index_version=version
        )
        remaining = store.repository.rows(store.collection_name, with_vectors=True)
        assert len(remaining) == 2
        assert all(r.vector_id == original[r.chunk.chunk_id] for r in remaining)
        assert all(r.vector.tolist() == [[2.0, 0.0]] for r in remaining)
    finally:
        store.close()
