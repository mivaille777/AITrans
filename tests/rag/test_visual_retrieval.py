from __future__ import annotations

from pathlib import Path

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.index_manifest import IndexManifestRecord, IndexStatus
from backend.rag.index_service import IndexDocumentResult
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.visual_retrieval import (
    VisualAwareIndexService,
    VisualIndexCoordinator,
    VisualRetrievalService,
    create_visual_embedding_provider,
    visual_retrieval_index_version,
    weighted_rrf_fuse,
)


def _chunk(chunk_id: str, *, document_id: str = "doc-1", page: int = 1) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"Evidence for {chunk_id}",
        title="Paper",
        page_number=page,
        chunk_index=max(0, page - 1),
        token_count=10,
        source_uri="file:///paper.pdf",
        document_hash="hash-v1",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        embedding_version="embedding-v1",
        metadata={"source_kind": "pdf"},
    )


def _candidate(chunk_id: str, rank: int, *, channel: str = "text") -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=_chunk(chunk_id, page=rank),
        rank=rank,
        metadata={"retrieval_channel": channel},
    )


class FakeBaseRetrieval:
    def __init__(self) -> None:
        self.calls = []

    def retrieve(self, query: str, **kwargs) -> RetrievalResult:
        self.calls.append((query, kwargs))
        candidates = [_candidate("text-a", 1), _candidate("shared", 2), _candidate("text-c", 3)]
        return RetrievalResult(
            query=query,
            candidates=candidates,
            retrieval_strategy="hybrid",
            metadata={"base": True},
        )


class FakeVisualProvider:
    model_name = "fake-colqwen"
    dimension = 2

    def __init__(self, *, fail_query: bool = False) -> None:
        self.fail_query = fail_query
        self.query_calls = 0
        self.image_calls = 0

    def embed_query(self, query: str):
        self.query_calls += 1
        if self.fail_query:
            raise RuntimeError("visual query unavailable")
        return [[1.0, 0.0], [0.0, 1.0]]

    def embed_images(self, image_paths):
        self.image_calls += 1
        return [[[1.0, 0.0]] for _path in image_paths]

    def close(self) -> None:
        return None


class FakeVisualStore:
    def __init__(self, *, already_indexed: bool = False) -> None:
        self.already_indexed = already_indexed
        self.search_calls = 0
        self.replace_calls = []
        self.deleted = []

    def search(self, query, *, top_k, filters=None):
        self.search_calls += 1
        return [
            _candidate("visual-a", 1, channel="visual"),
            _candidate("shared", 2, channel="visual"),
        ][:top_k]

    def has_document(self, document_id: str, *, index_version: str) -> bool:
        return self.already_indexed

    def replace_document(self, document_id, chunks, vectors, *, index_version):
        self.replace_calls.append((document_id, chunks, vectors, index_version))
        self.already_indexed = True

    def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class FakeManifest:
    def __init__(self, record: IndexManifestRecord) -> None:
        self.record = record

    def get(self, document_id: str):
        return self.record if document_id == self.record.document_id else None


class FakeBaseIndex:
    def __init__(self, *, result: IndexDocumentResult) -> None:
        self.result = result
        self.index_calls = 0
        self.delete_calls = 0

    def index_document(self, path):
        self.index_calls += 1
        return self.result

    def reindex_document(self, path):
        return self.result

    def delete_document(self, document_id):
        self.delete_calls += 1
        return True

    def get_index_status(self, document_id):
        return None


def _visual_config(**updates) -> RagVisualRetrievalConfig:
    values = {"enabled": True, "dimension": 2, "text_candidate_pool": 3, "visual_top_k": 3}
    values.update(updates)
    return RagVisualRetrievalConfig(**values)


def test_visual_retrieval_is_disabled_by_default() -> None:
    config = RagVisualRetrievalConfig()
    assert config.enabled is False
    assert create_visual_embedding_provider(config) is None
    assert RagVisualRetrievalConfig(model_family="colqwen2.5").model_family == "colqwen2_5"


def test_visual_index_version_tracks_semantic_configuration() -> None:
    base = _visual_config(dimension=128)
    assert visual_retrieval_index_version(base) != visual_retrieval_index_version(
        base.model_copy(update={"model": "another/model"})
    )
    assert visual_retrieval_index_version(base) != visual_retrieval_index_version(
        base.model_copy(update={"render_dpi": 180})
    )


def test_weighted_rrf_is_deterministic_and_merges_channels() -> None:
    text = [_candidate("shared", 1), _candidate("text", 2)]
    visual = [_candidate("visual", 1, channel="visual"), _candidate("shared", 2, channel="visual")]
    fused = weighted_rrf_fuse(
        [(text, 1.0, "text"), (visual, 1.5, "visual")],
        limit=3,
        k=10,
    )
    assert [item.chunk.chunk_id for item in fused] == ["shared", "visual", "text"]
    assert fused[0].metadata["fusion_channels"] == ["text", "visual"]
    assert [item.rank for item in fused] == [1, 2, 3]


def test_visual_retrieval_fuses_with_text_pool() -> None:
    base = FakeBaseRetrieval()
    provider = FakeVisualProvider()
    store = FakeVisualStore()
    service = VisualRetrievalService(
        base=base,
        provider=provider,
        store=store,
        config=_visual_config(text_weight=1.0, visual_weight=1.0),
        default_final_top_k=2,
    )
    result = service.retrieve("diagram", final_top_k=2)
    assert result.retrieval_strategy == "hybrid+visual-rrf"
    assert len(result.candidates) == 2
    assert result.metadata["visual_count"] == 2
    assert result.metadata["final_count"] == 2
    assert base.calls[0][1]["final_top_k"] == 3


def test_visual_query_failure_returns_text_only_candidates() -> None:
    base = FakeBaseRetrieval()
    provider = FakeVisualProvider(fail_query=True)
    service = VisualRetrievalService(
        base=base,
        provider=provider,
        store=FakeVisualStore(),
        config=_visual_config(),
        default_final_top_k=2,
    )
    result = service.retrieve("diagram")
    assert result.retrieval_strategy == "hybrid+visual-fallback"
    assert [item.chunk.chunk_id for item in result.candidates] == ["text-a", "shared"]
    assert "visual query unavailable" in result.metadata["visual_fallback_reason"]


def test_visual_index_reuse_skips_image_encoding(tmp_path: Path) -> None:
    record = IndexManifestRecord(
        document_id="doc-1",
        content_hash="hash-v1",
        source_uri=(tmp_path / "paper.pdf").as_uri(),
        title="Paper",
        status=IndexStatus.READY,
    )
    provider = FakeVisualProvider()
    store = FakeVisualStore(already_indexed=True)
    builder_calls = []

    def builder(source, current_record, config):
        builder_calls.append(source)
        return []

    coordinator = VisualIndexCoordinator(
        config=_visual_config(asset_storage_path=str(tmp_path / "assets")),
        provider=provider,
        store=store,
        manifest=FakeManifest(record),
        item_builder=builder,
    )
    assert coordinator.ensure_document(tmp_path / "paper.pdf", "doc-1") == 0
    assert builder_calls == []
    assert provider.image_calls == 0


def test_visual_index_missing_sidecar_is_created(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    asset = tmp_path / "page.png"
    asset.write_bytes(b"png")
    record = IndexManifestRecord(
        document_id="doc-1",
        content_hash="hash-v1",
        source_uri=source.as_uri(),
        title="Paper",
        status=IndexStatus.READY,
    )
    provider = FakeVisualProvider()
    store = FakeVisualStore(already_indexed=False)

    def builder(_source, _record, _config):
        return [(_chunk("visual-page"), asset)]

    coordinator = VisualIndexCoordinator(
        config=_visual_config(asset_storage_path=str(tmp_path / "assets")),
        provider=provider,
        store=store,
        manifest=FakeManifest(record),
        item_builder=builder,
    )
    assert coordinator.ensure_document(source, "doc-1") == 1
    assert provider.image_calls == 1
    assert len(store.replace_calls) == 1


def test_visual_sidecar_failure_does_not_fail_text_index(tmp_path: Path) -> None:
    result = IndexDocumentResult(
        document_id="doc-1",
        status=IndexStatus.READY,
        chunk_count=4,
        content_hash="hash-v1",
    )
    base = FakeBaseIndex(result=result)

    class FailingCoordinator:
        def ensure_document(self, *args, **kwargs):
            raise RuntimeError("gpu unavailable")

        def delete_document(self, document_id):
            return None

    service = VisualAwareIndexService(base, FailingCoordinator(), FakeManifest(IndexManifestRecord(document_id="doc-1")))
    returned = service.index_document(tmp_path / "paper.pdf")
    assert returned.status is IndexStatus.READY
    assert returned.chunk_count == 4
    assert base.index_calls == 1
