from __future__ import annotations

from backend.rag.benchmarks.runtime import build_benchmark_rag_runtime
from backend.rag.config import RagConfig, RagEmbeddingConfig
from backend.rag.models import DocumentChunk


class _FakeEmbedding:
    dimension = 2
    model_name = "test-embedding"

    def embed_query(self, _text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _chunk(document_id: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"chunk-{document_id}",
        document_id=document_id,
        text="benchmark-only evidence",
        title="Paper",
        section_heading="Results",
        section_path=["Results"],
        chunk_index=0,
    )


def test_benchmark_runtimes_use_distinct_qdrant_and_bm25_storage(tmp_path) -> None:
    embedding = _FakeEmbedding()
    config = RagConfig(embedding=RagEmbeddingConfig(dimension=2))
    left = build_benchmark_rag_runtime(
        tmp_path / "left", config=config, embedding_provider=embedding
    )
    right = build_benchmark_rag_runtime(
        tmp_path / "right", config=config, embedding_provider=embedding
    )
    try:
        left.vector_store.upsert_chunks([_chunk("left-paper")], [[1.0, 0.0]])
        left.sparse_retriever.index_chunks([_chunk("left-paper")])

        assert left.config.vector_store.storage_path != right.config.vector_store.storage_path
        assert left.vector_store.collection_name != right.vector_store.collection_name
        assert right.vector_store.search([1.0, 0.0], top_k=5) == []
        assert right.sparse_retriever.search("benchmark evidence", 5) == []
        assert not (tmp_path / "config" / "rag" / "qdrant").exists()
    finally:
        left.close()
        right.close()


def test_benchmark_runtime_rejects_production_storage_path(tmp_path, monkeypatch) -> None:
    production = (tmp_path / "config" / "rag" / "qdrant").resolve()
    monkeypatch.chdir(tmp_path)
    try:
        build_benchmark_rag_runtime(production, embedding_provider=_FakeEmbedding())
    except ValueError as exc:
        assert "production RAG storage" in str(exc)
    else:
        raise AssertionError("production RAG storage must be rejected")
