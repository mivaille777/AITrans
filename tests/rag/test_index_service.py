from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagChunkingConfig
from backend.rag.index_manifest import (
    IndexGenerationStatus,
    IndexManifest,
    IndexStatus,
)
from backend.rag.index_service import IndexService
from backend.rag.models import DocumentChunk, KnowledgeDocument, NormalizedDocument


class FakeParser:
    def __init__(self, *, version: str = "fake-parser-v1") -> None:
        self.version = version
        self.fail = False
        self.calls = 0

    def __call__(self, path: str | Path) -> NormalizedDocument:
        self.calls += 1
        if self.fail:
            raise RuntimeError("parser failed")
        source = Path(path)
        raw = source.read_bytes()
        text = raw.decode("utf-8")
        content_hash = sha256(raw).hexdigest()
        return NormalizedDocument(
            document=KnowledgeDocument(
                document_id="parser_document_id",
                title=source.stem,
                source_uri=source.resolve().as_uri(),
                source_kind="text",
                mime_type="text/plain",
                language="en",
                content_hash=content_hash,
            ),
            text=text,
            metadata={"parser_version": self.version},
        )


class FakeEmbeddingProvider:
    def __init__(self, *, model_name: str = "fake-model", dimension: int = 4) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self.calls: list[list[str]] = []
        self.fail = False

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding failed")
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.chunks: dict[str, DocumentChunk] = {}
        self.generations: dict[str, dict[str, DocumentChunk]] = {}
        self.fail = False
        self.fail_after_write = False
        self.upsert_calls = 0
        self.deleted_chunk_ids: list[str] = []

    def ensure_collection(self) -> None:
        return None

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        generation_id: str | None = None,
    ) -> None:
        assert len(chunks) == len(vectors)
        self.upsert_calls += 1
        if self.fail:
            raise RuntimeError("vector store failed")
        target = (
            self.chunks
            if generation_id is None
            else self.generations.setdefault(generation_id, {})
        )
        target.update({chunk.chunk_id: chunk for chunk in chunks})
        if self.fail_after_write:
            self.fail_after_write = False
            raise RuntimeError("vector store failed after write")

    def search(self, *_args, **_kwargs):
        return []

    def delete_document(
        self, document_id: str, *, generation_id: str | None = None
    ) -> None:
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }
        for current_generation, stored in list(self.generations.items()):
            if generation_id and current_generation != generation_id:
                continue
            self.generations[current_generation] = {
                chunk_id: chunk
                for chunk_id, chunk in stored.items()
                if chunk.document_id != document_id
            }

    def delete_chunks(
        self, chunk_ids: list[str], *, generation_id: str | None = None
    ) -> None:
        self.deleted_chunk_ids.extend(chunk_ids)
        target = (
            self.chunks
            if generation_id is None
            else self.generations.get(generation_id, {})
        )
        for chunk_id in chunk_ids:
            target.pop(chunk_id, None)

    def get_chunk(
        self, chunk_id: str, *, generation_id: str | None = None
    ) -> DocumentChunk | None:
        target = (
            self.chunks
            if generation_id is None
            else self.generations.get(generation_id, {})
        )
        return target.get(chunk_id)

    def list_chunks(self, *, generation_id: str | None = None) -> list[DocumentChunk]:
        target = (
            self.chunks
            if generation_id is None
            else self.generations.get(generation_id, {})
        )
        return list(target.values())


class FakeSparseRetriever:
    def __init__(self) -> None:
        self.generations: dict[str, dict[str, DocumentChunk]] = {}
        self.fail_after_write = False

    def index_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        generation_id: str | None = None,
    ) -> None:
        target = self.generations.setdefault(generation_id or "legacy", {})
        target.update({chunk.chunk_id: chunk for chunk in chunks})
        if self.fail_after_write:
            self.fail_after_write = False
            raise RuntimeError("BM25 store failed after write")

    def list_chunks(
        self,
        *,
        generation_id: str | None = None,
    ) -> list[DocumentChunk]:
        return list(self.generations.get(generation_id or "legacy", {}).values())

    def delete_document(
        self,
        document_id: str,
        *,
        generation_id: str | None = None,
    ) -> None:
        for stored_generation, chunks in list(self.generations.items()):
            if generation_id is not None and stored_generation != generation_id:
                continue
            self.generations[stored_generation] = {
                chunk_id: chunk
                for chunk_id, chunk in chunks.items()
                if chunk.document_id != document_id
            }


def make_service(
    tmp_path: Path,
    *,
    parser: FakeParser | None = None,
    embedding: FakeEmbeddingProvider | None = None,
    store: FakeVectorStore | None = None,
    sparse: FakeSparseRetriever | None = None,
) -> tuple[
    IndexService,
    FakeParser,
    FakeEmbeddingProvider,
    FakeVectorStore,
    IndexManifest,
]:
    selected_parser = parser or FakeParser()
    selected_embedding = embedding or FakeEmbeddingProvider()
    selected_store = store or FakeVectorStore()
    manifest = IndexManifest(tmp_path / "index_manifest.json")
    service = IndexService(
        chunker=StructureAwareChunker(
            RagChunkingConfig(
                target_tokens=20,
                overlap_tokens=4,
                minimum_tokens=3,
            )
        ),
        embedding_provider=selected_embedding,
        vector_store=selected_store,
        manifest=manifest,
        parser=selected_parser,
        sparse_retriever=sparse,
    )
    return service, selected_parser, selected_embedding, selected_store, manifest


def test_normal_document_indexing(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text(
        "Gaussian process optimization improves PID tuning.", encoding="utf-8"
    )
    service, _parser, embedding, store, manifest = make_service(tmp_path)

    result = service.index_document(path)

    assert result.status is IndexStatus.READY
    assert result.chunk_count == 1
    assert result.error == ""
    assert len(embedding.calls) == 1
    record = manifest.get(result.document_id)
    assert record is not None
    assert len(store.list_chunks(generation_id=record.generation_id)) == 1
    assert record.status is IndexStatus.READY
    assert record.chunk_ids == [
        chunk.chunk_id
        for chunk in store.list_chunks(generation_id=record.generation_id)
    ]


def test_duplicate_index_skips_embedding_and_vector_upsert(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Stable document content.", encoding="utf-8")
    service, _parser, embedding, store, _manifest = make_service(tmp_path)
    first = service.index_document(path)

    second = service.index_document(path)

    assert first.document_id == second.document_id
    assert second.reused_existing is True
    assert len(embedding.calls) == 1
    assert store.upsert_calls == 1


def test_changed_content_publishes_new_generation_and_retains_old(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("First content version.", encoding="utf-8")
    service, _parser, embedding, store, _manifest = make_service(tmp_path)
    first = service.index_document(path)
    first_record = _manifest_record(service, first.document_id)
    old_generation = first_record.generation_id
    old_chunk_ids = {
        chunk.chunk_id for chunk in store.list_chunks(generation_id=old_generation)
    }
    path.write_text("Second content version with changed evidence.", encoding="utf-8")

    second = service.index_document(path)

    assert second.status is IndexStatus.READY
    assert second.document_id == first.document_id
    assert second.content_hash != first.content_hash
    assert len(embedding.calls) == 2
    second_record = _manifest_record(service, first.document_id)
    assert second_record.generation_id != old_generation
    assert old_chunk_ids == {
        chunk.chunk_id for chunk in store.list_chunks(generation_id=old_generation)
    }
    assert (
        service._manifest.get_generation(first.document_id, old_generation).status
        is IndexGenerationStatus.RETIRED
    )
    assert store.deleted_chunk_ids == []


def test_embedding_model_change_reindexes(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Model fingerprint content.", encoding="utf-8")
    store = FakeVectorStore()
    first_service, parser, first_embedding, _store, _manifest = make_service(
        tmp_path,
        store=store,
    )
    first_service.index_document(path)
    second_embedding = FakeEmbeddingProvider(model_name="fake-model-v2")
    second_service, *_ = make_service(
        tmp_path,
        parser=parser,
        embedding=second_embedding,
        store=store,
    )

    result = second_service.index_document(path)

    assert result.reused_existing is False
    assert len(first_embedding.calls) == 1
    assert len(second_embedding.calls) == 1
    assert store.upsert_calls == 2


def test_parser_version_change_reindexes(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Parser fingerprint content.", encoding="utf-8")
    parser = FakeParser(version="v1")
    service, _parser, embedding, _store, _manifest = make_service(
        tmp_path,
        parser=parser,
    )
    service.index_document(path)
    parser.version = "v2"

    result = service.index_document(path)

    assert result.reused_existing is False
    assert len(embedding.calls) == 2


def test_parser_failure_leaves_old_vectors_intact(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Existing indexed content.", encoding="utf-8")
    service, parser, _embedding, store, manifest = make_service(tmp_path)
    first = service.index_document(path)
    old_chunks = _all_fake_chunks(store)
    parser.fail = True

    failed = service.reindex_document(first.document_id)

    assert failed.status is IndexStatus.FAILED
    assert failed.error == "parser failed"
    assert _all_fake_chunks(store) == old_chunks
    assert manifest.get(first.document_id).status is IndexStatus.READY


def test_embedding_failure_leaves_old_vectors_intact(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Existing indexed content.", encoding="utf-8")
    service, _parser, embedding, store, _manifest = make_service(tmp_path)
    first = service.index_document(path)
    old_chunks = _all_fake_chunks(store)
    embedding.fail = True

    failed = service.reindex_document(first.document_id)

    assert failed.status is IndexStatus.FAILED
    assert failed.error == "embedding failed"
    assert _all_fake_chunks(store) == old_chunks


def test_vector_store_failure_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Content that cannot be stored.", encoding="utf-8")
    store = FakeVectorStore()
    store.fail = True
    service, _parser, _embedding, _store, manifest = make_service(
        tmp_path,
        store=store,
    )

    result = service.index_document(path)

    assert result.status is IndexStatus.FAILED
    assert result.error == "vector store failed"
    assert manifest.get(result.document_id).status is IndexStatus.FAILED


def test_delete_removes_vectors_and_manifest(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Document to delete.", encoding="utf-8")
    service, _parser, _embedding, store, manifest = make_service(tmp_path)
    indexed = service.index_document(path)

    assert service.delete_document(indexed.document_id) is True
    assert service.delete_document(indexed.document_id) is False
    assert _all_fake_chunks(store) == {}
    assert manifest.get(indexed.document_id) is None


def test_manifest_is_loaded_after_service_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("Persistent manifest content.", encoding="utf-8")
    store = FakeVectorStore()
    first_service, parser, embedding, _store, _manifest = make_service(
        tmp_path,
        store=store,
    )
    first = first_service.index_document(path)
    second_service, *_ = make_service(
        tmp_path,
        parser=parser,
        embedding=embedding,
        store=store,
    )

    second = second_service.index_document(path)

    assert second.document_id == first.document_id
    assert second.reused_existing is True
    assert (
        second_service.get_index_status(first.document_id).status is IndexStatus.READY
    )


def test_vector_write_failure_preserves_old_active_generation(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("First committed generation.", encoding="utf-8")
    service, _parser, _embedding, store, manifest = make_service(tmp_path)
    first = service.index_document(path)
    old_record = _manifest_record(service, first.document_id)
    old_generation = old_record.generation_id
    path.write_text("Second generation fails after vector write.", encoding="utf-8")
    store.fail_after_write = True

    failed = service.reindex_document(first.document_id)

    assert failed.status is IndexStatus.FAILED
    active = manifest.get(first.document_id)
    assert active.generation_id == old_generation
    assert active.status is IndexStatus.READY
    assert store.list_chunks(generation_id=old_generation)
    failed_generations = [
        item
        for item in manifest.list_generations(first.document_id)
        if item.status is IndexGenerationStatus.FAILED
    ]
    assert len(failed_generations) == 1
    assert store.list_chunks(generation_id=failed_generations[0].generation_id) == []


def test_bm25_write_failure_preserves_old_active_generation(tmp_path: Path) -> None:
    path = tmp_path / "paper.txt"
    path.write_text("First committed generation.", encoding="utf-8")
    sparse = FakeSparseRetriever()
    service, _parser, _embedding, store, manifest = make_service(
        tmp_path,
        sparse=sparse,
    )
    first = service.index_document(path)
    old_generation = _manifest_record(service, first.document_id).generation_id
    path.write_text("Second generation fails after BM25 write.", encoding="utf-8")
    sparse.fail_after_write = True

    failed = service.reindex_document(first.document_id)

    assert failed.status is IndexStatus.FAILED
    active = manifest.get(first.document_id)
    assert active.generation_id == old_generation
    assert active.status is IndexStatus.READY
    assert store.list_chunks(generation_id=old_generation)
    assert sparse.list_chunks(generation_id=old_generation)
    failed_generations = [
        item
        for item in manifest.list_generations(first.document_id)
        if item.status is IndexGenerationStatus.FAILED
    ]
    assert len(failed_generations) == 1
    assert store.list_chunks(generation_id=failed_generations[0].generation_id) == []
    assert sparse.list_chunks(generation_id=failed_generations[0].generation_id) == []


def _manifest_record(service: IndexService, document_id: str):
    record = service.get_index_status(document_id)
    assert record is not None
    return record


def _all_fake_chunks(store: FakeVectorStore) -> dict[str, DocumentChunk]:
    chunks = dict(store.chunks)
    for generation_chunks in store.generations.values():
        chunks.update(generation_chunks)
    return chunks
