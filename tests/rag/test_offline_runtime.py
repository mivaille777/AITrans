from __future__ import annotations

import json
import math
import socket
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import (
    RagChunkingConfig,
    RagEmbeddingConfig,
    RagRerankerConfig,
    RagRetrievalConfig,
)
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
from backend.rag.index_manifest import IndexManifest, IndexStatus
from backend.rag.index_service import IndexService
from backend.rag.model_manager import (
    EMBEDDING_MODEL_ID,
    MODEL_COMPLETION_MANIFEST,
    MODEL_SPECS,
    RERANKER_MODEL_ID,
    ModelManager,
)
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.rerankers.qwen3 import Qwen3RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever


class CpuTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False


class OfflineEmbeddingModel:
    @staticmethod
    def encode(texts, **_kwargs):
        return [
            [1.0, 0.0, 0.0, 0.0]
            if "gaussian" in text.lower() or "高斯" in text
            else [0.0, 1.0, 0.0, 0.0]
            for text in texts
        ]


class OfflineRerankerModel:
    @staticmethod
    def predict(pairs, **_kwargs):
        return [1.0 if "gaussian" in text.lower() else 0.1 for _query, text in pairs]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.entries: dict[str, tuple[DocumentChunk, list[float]]] = {}

    def upsert_chunks(self, chunks, vectors) -> None:
        self.entries.update(
            {
                chunk.chunk_id: (chunk, vector)
                for chunk, vector in zip(chunks, vectors, strict=True)
            }
        )

    def search(self, vector, *, top_k, filters=None):
        def score(candidate):
            _chunk, stored = candidate
            return sum(left * right for left, right in zip(vector, stored, strict=True))

        eligible = [
            entry
            for entry in self.entries.values()
            if filters is None
            or not filters.document_ids
            or entry[0].document_id in filters.document_ids
        ]
        ranked = sorted(eligible, key=score, reverse=True)[:top_k]
        return [
            RetrievalCandidate(
                chunk=chunk,
                dense_score=score((chunk, stored)),
                rank=rank,
            )
            for rank, (chunk, stored) in enumerate(ranked, start=1)
        ]

    def delete_document(self, document_id):
        self.entries = {
            chunk_id: entry
            for chunk_id, entry in self.entries.items()
            if entry[0].document_id != document_id
        }

    def delete_chunks(self, chunk_ids):
        for chunk_id in chunk_ids:
            self.entries.pop(chunk_id, None)


def _installed_manager(root: Path) -> ModelManager:
    manager = ModelManager(root, downloader=lambda **_kwargs: None)
    for model_id in (EMBEDDING_MODEL_ID, RERANKER_MODEL_ID):
        spec = MODEL_SPECS[model_id]
        target = root / spec.directory_name
        target.mkdir(parents=True)
        for name in spec.required_files:
            (target / name).write_text("fixture", encoding="utf-8")
        (target / spec.required_any[0][0]).write_bytes(b"weights")
        (target / MODEL_COMPLETION_MANIFEST).write_text(
            json.dumps({"model_id": model_id, "repository_id": spec.repository_id}),
            encoding="utf-8",
        )
    return manager


def test_installed_local_runtime_indexes_and_retrieves_without_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    network_attempts = []

    def reject_network(_socket, address):
        network_attempts.append(address)
        raise AssertionError(f"unexpected network access: {address}")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    manager = _installed_manager(tmp_path / "models")
    embedding_calls = []
    reranker_calls = []

    def embedding_factory(*args, **kwargs):
        embedding_calls.append((args, kwargs))
        return OfflineEmbeddingModel()

    def reranker_factory(*args, **kwargs):
        reranker_calls.append((args, kwargs))
        return OfflineRerankerModel()

    embedding = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(dimension=4, device="cpu", warmup=False),
        model_factory=embedding_factory,
        torch_module=CpuTorch(),
        model_manager=manager,
    )
    reranker = Qwen3RerankerProvider(
        RagRerankerConfig(device="cpu"),
        model_factory=reranker_factory,
        torch_module=CpuTorch(),
        model_manager=manager,
    )
    vector_store = InMemoryVectorStore()
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    index = IndexService(
        chunker=StructureAwareChunker(
            RagChunkingConfig(
                target_tokens=20,
                overlap_tokens=4,
                minimum_tokens=3,
            )
        ),
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=IndexManifest(tmp_path / "manifest.json"),
    )
    source = tmp_path / "paper.txt"
    source.write_text(
        "Gaussian processes improve robust PID tuning.\n\n"
        "A separate appendix discusses deterministic controls.",
        encoding="utf-8",
    )

    indexed = index.index_document(source)
    retrieval = RetrievalService(
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        config=RagRetrievalConfig(
            dense_top_k=5,
            sparse_top_k=5,
            fusion_top_k=5,
            final_top_k=2,
        ),
        reranker=reranker,
    ).retrieve("How are Gaussian processes used?")

    assert indexed.status is IndexStatus.READY
    assert retrieval.candidates
    assert "Gaussian" in retrieval.candidates[0].chunk.text
    assert retrieval.candidates[0].rerank_score == 1
    assert embedding_calls[0][1]["local_files_only"] is True
    assert reranker_calls[0][1]["local_files_only"] is True
    assert math.isfinite(retrieval.elapsed_ms)
    assert network_attempts == []


def test_sidecar_packaging_declares_runtime_code_and_excludes_weights() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = (root / "aitrans_backend.spec").read_text(encoding="utf-8")
    build_script = (root / "scripts" / "build_rag_backend.ps1").read_text(
        encoding="utf-8"
    )

    for package in ("sentence_transformers", "transformers", "qdrant_client"):
        assert package in spec
    assert "backend/sidecar.py" not in spec
    assert '"backend" / "sidecar.py"' in spec
    assert "model.safetensors" in spec
    assert "pytorch_model.bin" in spec
    assert "HF_HUB_OFFLINE" in build_script
    assert "TRANSFORMERS_OFFLINE" in build_script
    assert "--runtime-smoke-test" in build_script
