from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.knowledge_dependencies import get_knowledge_library_service
from backend.main import create_app
from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import (
    RagChunkingConfig,
    RagConfig,
    RagEmbeddingConfig,
    RagVectorStoreConfig,
)
from backend.rag.index_manifest import IndexManifest
from backend.rag.index_service import IndexService
from backend.rag.models import DocumentChunk, KnowledgeDocument, NormalizedDocument
from backend.services.knowledge_library_service import KnowledgeLibraryService


class FakeEmbedding:
    model_name = "fake-embedding"
    dimension = 4
    runtime = SimpleNamespace(status="ready", device="cpu")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _text in texts]


class FailingEmbedding(FakeEmbedding):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        _ = texts
        raise RuntimeError("embedding runtime unavailable")


class FakeVectorStore:
    def __init__(self) -> None:
        self.chunks: dict[str, DocumentChunk] = {}

    def upsert_chunks(self, chunks, vectors) -> None:
        assert len(chunks) == len(vectors)
        self.chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def delete_document(self, document_id: str) -> None:
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for chunk_id in chunk_ids:
            self.chunks.pop(chunk_id, None)


class FakeSparse:
    def __init__(self) -> None:
        self.chunks: dict[str, DocumentChunk] = {}

    def index_chunks(self, chunks: list[DocumentChunk]) -> None:
        self.chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def delete_document(self, document_id: str) -> None:
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }


def _parse(path: str | Path) -> NormalizedDocument:
    source = Path(path)
    raw = source.read_bytes()
    return NormalizedDocument(
        document=KnowledgeDocument(
            document_id="parser-id",
            title=source.stem,
            source_uri=source.resolve().as_uri(),
            source_kind="text",
            mime_type="text/plain",
            language="en",
            content_hash=sha256(raw).hexdigest(),
        ),
        text=raw.decode("utf-8"),
        metadata={"parser_version": "fake-parser-v1"},
    )


def _service(
    state_path: Path,
    allowed_root: Path,
    *,
    max_file_bytes: int = 1024,
    embedding=None,
) -> tuple[KnowledgeLibraryService, FakeVectorStore, FakeSparse]:
    manifest = IndexManifest(state_path / "manifest.json")
    embedding = embedding or FakeEmbedding()
    vector_store = FakeVectorStore()
    sparse = FakeSparse()
    config = RagConfig(
        chunking=RagChunkingConfig(
            target_tokens=20,
            overlap_tokens=4,
            minimum_tokens=3,
        ),
        embedding=RagEmbeddingConfig(
            provider="qwen3",
            model="fake-embedding",
            dimension=4,
            device="cpu",
        ),
        vector_store=RagVectorStoreConfig(
            storage_path=str(state_path / "qdrant"),
            collection_name="test-knowledge",
        ),
    )
    index = IndexService(
        chunker=StructureAwareChunker(config.chunking),
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=manifest,
        parser=_parse,
    )
    return (
        KnowledgeLibraryService(
            index_service=index,
            manifest=manifest,
            config=config,
            embedding_provider=embedding,
            allowed_roots=(allowed_root,),
            max_file_bytes=max_file_bytes,
        ),
        vector_store,
        sparse,
    )


def _client(service: KnowledgeLibraryService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_knowledge_library_service] = lambda: service
    return TestClient(app)


def test_knowledge_document_lifecycle_and_runtime(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "control.md"
    source.write_text("Gaussian processes improve robust PID tuning.", encoding="utf-8")
    service, vector_store, sparse = _service(tmp_path / "state", allowed)
    client = _client(service)

    imported = client.post("/api/knowledge/documents", json={"path": str(source)})
    assert imported.status_code == 201
    document = imported.json()["document"]
    document_id = document["document_id"]
    assert document["status"] == "ready"
    assert document["source_type"] == "md"
    assert document["chunk_count"] == 1
    assert vector_store.chunks
    assert sparse.chunks

    listed = client.get("/api/knowledge/documents")
    detail = client.get(f"/api/knowledge/documents/{document_id}")
    index_status = client.get(f"/api/knowledge/documents/{document_id}/status")
    runtime = client.get("/api/knowledge/runtime")
    assert listed.json()["total"] == 1
    assert detail.json()["title"] == "control"
    assert index_status.json()["status"] == "ready"
    assert runtime.json() == {
        "enabled": True,
        "embedding_provider": "qwen3",
        "embedding_model": "fake-embedding",
        "embedding_status": "ready",
        "device": "cpu",
        "dimension": 4,
        "vector_store_provider": "qdrant_local",
        "collection_name": "test-knowledge",
        "document_count": 1,
        "ready_document_count": 1,
        "indexed_chunk_count": 1,
        "max_file_bytes": 1024,
    }

    reindexed = client.post(f"/api/knowledge/documents/{document_id}/reindex")
    assert reindexed.status_code == 200
    assert reindexed.json()["document"]["status"] == "ready"

    deleted = client.delete(f"/api/knowledge/documents/{document_id}")
    assert deleted.json() == {
        "document_id": document_id,
        "deleted": True,
        "source_file_preserved": True,
    }
    assert source.exists()
    assert vector_store.chunks == {}
    assert sparse.chunks == {}
    assert client.get(f"/api/knowledge/documents/{document_id}").status_code == 404


def test_import_rejects_unsupported_missing_relative_and_oversized_files(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    unsupported = allowed / "payload.exe"
    unsupported.write_bytes(b"not a document")
    oversized = allowed / "large.txt"
    oversized.write_bytes(b"x" * 33)
    service, *_ = _service(tmp_path / "state", allowed, max_file_bytes=32)
    client = _client(service)

    assert (
        client.post(
            "/api/knowledge/documents", json={"path": str(unsupported)}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/knowledge/documents", json={"path": str(allowed / "missing.pdf")}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/knowledge/documents", json={"path": "relative.txt"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/knowledge/documents", json={"path": str(oversized)}
        ).status_code
        == 422
    )


def test_import_normalizes_path_and_rejects_escape_from_allowed_root(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    service, *_ = _service(tmp_path / "state", allowed)
    client = _client(service)

    escaped = allowed / ".." / "outside.txt"
    response = client.post(
        "/api/knowledge/documents",
        json={"path": str(escaped)},
    )

    assert response.status_code == 403


def test_import_returns_service_unavailable_when_indexing_fails(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "control.md"
    source.write_text("Gaussian process control.", encoding="utf-8")
    service, *_ = _service(
        tmp_path / "state",
        allowed,
        embedding=FailingEmbedding(),
    )
    client = _client(service)

    response = client.post("/api/knowledge/documents", json={"path": str(source)})

    assert response.status_code == 503
    assert "embedding runtime unavailable" in response.json()["detail"]
    listed = client.get("/api/knowledge/documents").json()
    assert listed["total"] == 1
    assert listed["documents"][0]["status"] == "failed"


def test_unknown_document_operations_return_not_found(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    service, *_ = _service(tmp_path / "state", allowed)
    client = _client(service)

    assert client.get("/api/knowledge/documents/missing").status_code == 404
    assert client.get("/api/knowledge/documents/missing/status").status_code == 404
    assert client.post("/api/knowledge/documents/missing/reindex").status_code == 404
    assert client.delete("/api/knowledge/documents/missing").status_code == 404
