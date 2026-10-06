from __future__ import annotations

from pathlib import Path

from backend.rag.config import RagVectorStoreConfig
from backend.rag.models import DocumentChunk
from backend.rag.stores import FaissVectorStore, VectorSearchFilter


def make_chunk(chunk_id: str, document_id: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"Evidence from {document_id}.",
        title=document_id,
        section_heading="Findings",
        page_number=1,
        chunk_index=0,
        paragraph_index=0,
        start_char=0,
        end_char=len(f"Evidence from {document_id}."),
        token_count=4,
        language="en",
        source_uri=f"file:///{document_id}.txt",
        document_hash=f"hash-{document_id}",
        parser_version="text-v1",
        chunker_version="chunker-v1",
        embedding_version="embedding-v1",
    )


def make_store(path: Path) -> FaissVectorStore:
    return FaissVectorStore(
        RagVectorStoreConfig(storage_path=str(path)),
        dimension=4,
    )


VECTOR = [1.0, 0.0, 0.0, 0.0]


def test_empty_or_disjoint_scope_returns_without_querying_faiss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "faiss")
    monkeypatch.setattr(
        store,
        "ensure_collection",
        lambda: (_ for _ in ()).throw(AssertionError("scope should short-circuit")),
    )

    assert (
        store.search(
            VECTOR,
            top_k=5,
            allowed_document_ids=[],
        )
        == []
    )
    assert (
        store.search(
            VECTOR,
            top_k=5,
            filters=VectorSearchFilter(document_ids=["requested"]),
            allowed_document_ids=["allowed"],
        )
        == []
    )
    store.close()


def test_scope_and_active_generation_filter_before_query_and_after_delete(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path / "faiss")
    try:
        allowed = make_chunk("chunk_allowed", "doc_allowed")
        stale = make_chunk("chunk_stale", "doc_allowed")
        private = make_chunk("chunk_private", "doc_private")
        store.upsert_chunks([allowed], [VECTOR], generation_id="generation-current")
        store.upsert_chunks([stale], [VECTOR], generation_id="generation-old")
        store.upsert_chunks([private], [VECTOR], generation_id="generation-current")
        filters = VectorSearchFilter()

        results = store.search(
            VECTOR,
            top_k=5,
            filters=filters,
            allowed_document_ids=["doc_allowed"],
            active_generations={
                "doc_allowed": "generation-current",
                "doc_private": "generation-current",
            },
        )

        assert [result.chunk.chunk_id for result in results] == ["chunk_allowed"]

        store.delete_document("doc_allowed", generation_id="generation-current")
        assert (
            store.search(
                VECTOR,
                top_k=5,
                filters=filters,
                allowed_document_ids=["doc_allowed"],
                active_generations={"doc_allowed": "generation-current"},
            )
            == []
        )
    finally:
        store.close()


def test_pre_filter_keeps_true_scoped_top_k(tmp_path):
    with make_store(tmp_path / "faiss") as store:
        chunks = [make_chunk(f"private-{i}", "private") for i in range(50)]
        chunks += [make_chunk("allowed", "allowed")]
        store.upsert_chunks(chunks, [VECTOR] * 50 + [[0.,1.,0.,0.]])
        hits = store.search(VECTOR, top_k=1, allowed_document_ids=["allowed"])
        assert [hit.chunk.chunk_id for hit in hits] == ["allowed"]


def test_corrupt_generation_is_rejected(tmp_path):
    import json
    import pytest
    from backend.rag.exceptions import RagVectorStoreError
    with make_store(tmp_path / "faiss") as store:
        store.upsert_chunks([make_chunk("a", "allowed")], [VECTOR], generation_id="g1")
        chunk = store.get_chunk("a", generation_id="g1").model_dump(mode="json")
        chunk["metadata"]["index_generation"] = "g2"
        store.repository.connection.execute("UPDATE items SET payload=?", (json.dumps(chunk),))
        with pytest.raises(RagVectorStoreError):
            store.search(VECTOR, top_k=1, active_generations={"allowed":"g1"})
