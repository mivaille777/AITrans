"""Real offline Qwen indexing, generation replacement, citations and delete smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import (
    RagEmbeddingConfig,
    RagRerankerConfig,
    RagVectorStoreConfig,
)
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
from backend.rag.index_manifest import IndexManifest, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.rerankers.qwen3 import Qwen3RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores.faiss import FaissVectorStore


def validate(output: Path, *, embedding_path: str, reranker_path: str):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "acceptance.txt"
    source.write_text(
        "FAISS stores a searchable vector index locally. SQLite preserves vectors and "
        "document metadata durably. The document contains experimental results and "
        "supports Chinese and English retrieval queries.",
        encoding="utf-8",
    )
    embedding = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(
            model_path=embedding_path,
            local_files_only=True,
            device="cuda",
            precision="bf16",
        )
    )
    reranker = Qwen3RerankerProvider(
        RagRerankerConfig(
            model_path=reranker_path,
            local_files_only=True,
            device="cuda",
        )
    )
    config = RagVectorStoreConfig(storage_path=str(output / "faiss"))
    store = FaissVectorStore(config, dimension=1024)
    sparse = BM25SparseRetriever(output / "bm25.json")
    manifest = IndexManifest(output / "manifest.json")

    def index_service():
        return IndexService(
            chunker=StructureAwareChunker(),
            embedding_provider=embedding,
            vector_store=store,
            sparse_retriever=sparse,
            manifest=manifest,
        )

    def retrieval_service():
        return RetrievalService(
            embedding_provider=embedding,
            vector_store=store,
            sparse_retriever=sparse,
            manifest=manifest,
            reranker=reranker,
        )

    try:
        service = index_service()
        first = service.index_document(source)
        assert first.status is IndexStatus.READY, first.error
        assert service.index_document(source).reused_existing
        g1 = manifest.get(first.document_id).generation_id
        retrieval = retrieval_service()
        results = []
        for query in (
            "Which storage preserves document metadata?",
            "哪个存储保存文档元数据？",
        ):
            result = retrieval.retrieve(query, small_to_big_enabled=False)
            assert result.candidates and result.metadata["dense_chunk_ids"], (
                result.metadata
            )
            assert not result.metadata.get("fallback_reason"), result.metadata
            assert not result.metadata.get("reranker_fallback_reason"), result.metadata
            retrieval.validate_evidence_candidates(result)
            results.append(
                {
                    "query": query,
                    "strategy": result.retrieval_strategy,
                    "candidates": len(result.candidates),
                    "evidence_validated": True,
                }
            )
        rebuilt = service.reindex_document(source)
        assert rebuilt.status is IndexStatus.READY, rebuilt.error
        g2 = manifest.get(first.document_id).generation_id
        assert g1 != g2
        assert store.list_chunks(generation_id=g1)
        active_result = retrieval.retrieve(
            "SQLite metadata", small_to_big_enabled=False
        )
        assert all(c.index_generation == g2 for c in active_result.candidates)
        retrieval.validate_evidence_candidates(active_result)
        store.close()
        store = FaissVectorStore(config, dimension=1024)
        restored = retrieval_service().retrieve(
            "SQLite metadata", small_to_big_enabled=False
        )
        assert restored.candidates and all(
            c.index_generation == g2 for c in restored.candidates
        )
        retrieval_service().validate_evidence_candidates(restored)
        assert index_service().delete_document(first.document_id)
        assert store.count_chunks() == 0 and sparse.list_chunks() == []
        assert (
            retrieval_service()
            .retrieve("SQLite metadata", small_to_big_enabled=False)
            .candidates
            == []
        )
        payload = {
            "status": "passed",
            "real_embedding_and_reranker": True,
            "index_reuse_reindex_reopen_delete": True,
            "queries": results,
            "retired_generation_preserved_until_delete": True,
        }
        (output / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False))
        return payload
    finally:
        store.close()
        for provider in (embedding, reranker):
            close = getattr(provider, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-path", required=True)
    parser.add_argument("--reranker-path", required=True)
    args = parser.parse_args()
    validate(
        args.output.resolve(),
        embedding_path=args.embedding_path,
        reranker_path=args.reranker_path,
    )
