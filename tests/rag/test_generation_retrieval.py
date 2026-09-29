from __future__ import annotations

from pathlib import Path

from backend.rag.config import RagRetrievalConfig, RagVectorStoreConfig
from backend.rag.index_manifest import IndexManifest, ready_manifest_record
from backend.rag.models import DocumentChunk
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse.store import BM25SparseRetriever
from backend.rag.stores import QdrantLocalVectorStore
from backend.rag.stores.base import VectorSearchFilter


class QueryEmbedding:
    model_name = "test-model"
    dimension = 4

    def embed_query(self, _query: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


def _chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "paper-a",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title="Paper A",
        page_number=1,
        chunk_index=0,
        language="en",
        metadata={"source_kind": "text"},
    )


def _publish(manifest: IndexManifest, generation_id: str, chunk_id: str) -> None:
    manifest.begin_generation("paper-a", generation_id, [chunk_id])
    manifest.validate_generation("paper-a", generation_id, [chunk_id])
    manifest.publish_generation("paper-a", generation_id)


def test_online_retrieval_sees_only_published_generation(tmp_path: Path) -> None:
    vector_store = QdrantLocalVectorStore(
        RagVectorStoreConfig(storage_path=str(tmp_path / "qdrant")),
        dimension=4,
    )
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    manifest = IndexManifest(tmp_path / "manifest.json")
    old_chunk = _chunk("old-chunk", "alpha evidence from the published version")
    legacy_chunk = _chunk(
        "legacy-chunk",
        "alpha evidence from a legacy document",
        document_id="paper-legacy",
    )
    staged_chunk = _chunk("staged-chunk", "alpha evidence from an unpublished version")
    try:
        manifest.upsert(
            ready_manifest_record(
                document_id="paper-a",
                content_hash="old-hash",
                source_uri="file:///paper-a.pdf",
                title="Paper A",
                parser_version="test-parser",
                chunker_version="test-chunker",
                embedding_model="test-model",
                embedding_dimension=4,
                chunk_ids=[old_chunk.chunk_id],
            )
        )
        manifest.upsert(
            ready_manifest_record(
                document_id="paper-legacy",
                content_hash="legacy-hash",
                source_uri="file:///paper-legacy.txt",
                title="Legacy Paper",
                parser_version="test-parser",
                chunker_version="test-chunker",
                embedding_model="test-model",
                embedding_dimension=4,
                chunk_ids=[legacy_chunk.chunk_id],
            )
        )
        _publish(manifest, "generation-old", old_chunk.chunk_id)
        vector_store.upsert_chunks(
            [old_chunk], [[1.0, 0.0, 0.0, 0.0]], generation_id="generation-old"
        )
        sparse.index_chunks([old_chunk], generation_id="generation-old")
        vector_store.upsert_chunks([legacy_chunk], [[0.9, 0.1, 0.0, 0.0]])
        sparse.index_chunks([legacy_chunk])
        vector_store.upsert_chunks(
            [staged_chunk],
            [[0.99, 0.01, 0.0, 0.0]],
            generation_id="generation-staged",
        )
        sparse.index_chunks([staged_chunk], generation_id="generation-staged")
        manifest.begin_generation(
            "paper-a", "generation-staged", [staged_chunk.chunk_id]
        )
        manifest.fail_generation(
            "paper-a", "generation-staged", error="injected write failure"
        )
        successful_chunk = _chunk(
            "next-chunk", "alpha evidence after successful publish"
        )
        vector_store.upsert_chunks(
            [successful_chunk],
            [[0.98, 0.02, 0.0, 0.0]],
            generation_id="generation-next",
        )
        sparse.index_chunks([successful_chunk], generation_id="generation-next")

        retrieval = RetrievalService(
            embedding_provider=QueryEmbedding(),
            vector_store=vector_store,
            sparse_retriever=sparse,
            config=RagRetrievalConfig(
                dense_top_k=10,
                sparse_top_k=10,
                fusion_top_k=10,
                final_top_k=10,
            ),
            manifest=manifest,
        )

        before_publish = retrieval.retrieve(
            "alpha evidence",
            reranker_enabled=False,
            small_to_big_enabled=False,
        )
        before_publish_ids = {item.chunk.chunk_id for item in before_publish.candidates}
        assert before_publish_ids == {"old-chunk", "legacy-chunk"}
        assert before_publish.metadata["active_generation_count"] == 2

        legacy_result = retrieval.retrieve(
            "alpha evidence",
            filters=VectorSearchFilter(document_ids=["paper-legacy"]),
            reranker_enabled=False,
            small_to_big_enabled=False,
        )
        assert [item.chunk.chunk_id for item in legacy_result.candidates] == [
            "legacy-chunk"
        ]

        manifest.begin_generation(
            "paper-a", "generation-next", [successful_chunk.chunk_id]
        )
        manifest.validate_generation(
            "paper-a", "generation-next", [successful_chunk.chunk_id]
        )
        manifest.publish_generation("paper-a", "generation-next")

        after_publish = retrieval.retrieve(
            "alpha evidence",
            reranker_enabled=False,
            small_to_big_enabled=False,
        )
        after_publish_ids = {item.chunk.chunk_id for item in after_publish.candidates}
        assert after_publish_ids == {"next-chunk", "legacy-chunk"}
    finally:
        vector_store.close()
