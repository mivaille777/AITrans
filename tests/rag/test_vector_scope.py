from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.rag.config import RagVectorStoreConfig
from backend.rag.models import DocumentChunk
from backend.rag.stores import QdrantLocalVectorStore, VectorSearchFilter


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


def make_store(path: Path) -> QdrantLocalVectorStore:
    return QdrantLocalVectorStore(
        RagVectorStoreConfig(storage_path=str(path)),
        dimension=4,
    )


VECTOR = [1.0, 0.0, 0.0, 0.0]


def test_empty_or_disjoint_scope_returns_without_querying_qdrant(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "qdrant")
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


def test_qdrant_filter_contains_allowlist_and_only_scoped_generations() -> None:
    query_filter = QdrantLocalVectorStore._build_filter(
        VectorSearchFilter(),
        active_generations={
            "doc_allowed": "generation-current",
            "doc_private": "generation-current",
        },
        allowed_document_ids=["doc_allowed"],
    )

    assert query_filter is not None
    assert query_filter.must[0].key == "document_id"
    assert query_filter.must[0].match.any == ["doc_allowed"]
    scoped_generation_filter = query_filter.must[1]
    assert len(scoped_generation_filter.should) == 1
    assert scoped_generation_filter.should[0].must[0].match.value == "doc_allowed"


def test_scope_and_active_generation_filter_before_query_and_after_delete(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path / "qdrant")
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


def test_post_filter_drops_out_of_scope_and_stale_generation_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        store.ensure_collection()
        valid = QdrantLocalVectorStore._chunk_payload(
            make_chunk("valid", "doc_allowed"),
            "generation-current",
        )
        private = QdrantLocalVectorStore._chunk_payload(
            make_chunk("private", "doc_private"),
            "generation-current",
        )
        stale = QdrantLocalVectorStore._chunk_payload(
            make_chunk("stale", "doc_allowed"),
            "generation-old",
        )
        stale["page_number"] = "corrupt stale generation payload"
        metadata_only = QdrantLocalVectorStore._chunk_payload(
            make_chunk("metadata-only", "doc_allowed"),
            "generation-current",
        )
        metadata_only.pop("index_generation")
        inconsistent = QdrantLocalVectorStore._chunk_payload(
            make_chunk("inconsistent", "doc_allowed"),
            "generation-current",
        )
        inconsistent["metadata"]["index_generation"] = "generation-old"
        points = [
            SimpleNamespace(payload=payload, score=1.0)
            for payload in (private, stale, metadata_only, inconsistent, valid)
        ]
        monkeypatch.setattr(
            store._client,
            "query_points",
            lambda **_kwargs: SimpleNamespace(points=points),
        )

        results = store.search(
            VECTOR,
            top_k=5,
            allowed_document_ids=["doc_allowed"],
            active_generations={"doc_allowed": "generation-current"},
        )

        assert [result.chunk.chunk_id for result in results] == ["valid"]
    finally:
        store.close()
