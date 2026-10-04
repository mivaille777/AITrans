from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.exceptions import RagRetrievalError, RagVectorStoreError
from backend.rag.index_manifest import IndexManifestRecord, IndexStatus
from backend.rag.index_service import IndexDocumentResult
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.visual_retrieval import (
    VisualAwareIndexService,
    VisualIndexCoordinator,
    VisualRetrievalService,
    build_visual_index_items,
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


def test_native_visual_quantization_and_resolution_change_index_identity():
    config = RagVisualRetrievalConfig()
    original = visual_retrieval_index_version(config)
    for field, value in (("quantization", "nf4"), ("max_image_tokens", 256), ("precision", "fp16")):
        assert visual_retrieval_index_version(config.model_copy(update={field: value})) != original
    with pytest.raises(ValueError):
        RagVisualRetrievalConfig(quantization="unsupported")


def test_native_visual_cpu_rejects_cuda_only_quantization(monkeypatch):
    import sys

    from backend.rag.exceptions import RagConfigurationError
    from backend.rag.visual_retrieval import ColPaliEngineVisualEmbeddingProvider

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float32="float32"))
    monkeypatch.setitem(sys.modules, "colpali_engine", SimpleNamespace(models=SimpleNamespace(
        ColQwen2_5=object(), ColQwen2_5_Processor=object())))
    provider = ColPaliEngineVisualEmbeddingProvider(RagVisualRetrievalConfig(device="cpu", quantization="nf4"))
    with pytest.raises(RagConfigurationError, match="requires CUDA"):
        provider.embed_query("chart")


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


@pytest.fixture(params=[False, True])
def published_visual(request, tmp_path):
    from backend.rag.visual_adaptive import (
        AdaptiveVisualRetrievalService,
        create_adaptive_visual_vector_store,
    )

    source = tmp_path / "paper.pdf"
    import fitz
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "The sample contains a blue chart.")
        pdf.save(source)
    record = IndexManifestRecord(document_id="doc-1", status=IndexStatus.READY,
        generation_id="g1", content_hash=sha256(source.read_bytes()).hexdigest(), source_uri=source.as_uri())
    config = _visual_config(prefetch_enabled=request.param, render_dpi=72,
        asset_storage_path=str(tmp_path / "assets"))
    client = QdrantClient(":memory:")
    store = create_adaptive_visual_vector_store(config, client=client)
    manifest = FakeManifest(record)
    base = SimpleNamespace(
        _manifest=manifest,
        _resolve_active_generations=lambda filters: (
            {"doc-1": manifest.record.generation_id or None}
            if manifest.record and (not filters.document_ids or "doc-1" in filters.document_ids) else {}),
        get_active_chunk=lambda *args, **kwargs: None,
        evidence_cache_version=lambda **kwargs: manifest.record.generation_id if manifest.record else "deleted",
        validate_evidence_candidates=lambda result, **kwargs: None,
    )
    def retrieve(query, **kwargs):
        now = datetime.now(UTC).isoformat()
        return RetrievalResult(query=query, candidates=[], metadata={
            "active_generations": base._resolve_active_generations(kwargs.get("filters") or VectorSearchFilter()),
            "retrieval_span": {"trace_id": kwargs.get("trace_id", "fixture-trace"),
                "span_id": "fixture-retrieval", "parent_id": "fixture-root", "stage": "retrieval",
                "status": "complete", "started_at": now, "ended_at": now, "elapsed_ms": 0.0},
        })
    from backend.rag.stores.base import VectorSearchFilter
    base.retrieve = retrieve
    coordinator = VisualIndexCoordinator(config=config, provider=FakeVisualProvider(), store=store, manifest=manifest)
    assert coordinator.ensure_document(source, "doc-1") == 1
    service = AdaptiveVisualRetrievalService(base=base, provider=FakeVisualProvider(), store=store,
        config=config, default_final_top_k=2)
    yield service, coordinator, store, manifest, source, config
    client.close()


def test_native_visual_retrieval_validation_jit_and_scope(published_visual):
    from backend.rag.stores.base import VectorSearchFilter
    service, _, _, _, _, _ = published_visual
    result = service.retrieve("blue chart", dense_enabled=False, trace_id="visual-trace")
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.index_generation == "g1"
    assert candidate.channel_hits[0].channel == "visual"
    assert result.elapsed_ms > 0
    assert result.metadata["total_rag_ms"] == result.elapsed_ms
    visual_span = result.metadata["stage_timings"]["visual"]
    assert visual_span["trace_id"] == "visual-trace"
    assert visual_span["status"] == "complete"
    assert visual_span["elapsed_ms"] > 0
    assert visual_span["started_at"] <= visual_span["ended_at"]
    assert result.elapsed_ms >= visual_span["elapsed_ms"]
    service.validate_evidence_candidates(result)
    assert service.get_active_chunk(candidate.chunk.chunk_id) == candidate.chunk
    forbidden = VectorSearchFilter(document_ids=["other"])
    assert service.retrieve("blue chart", filters=forbidden).candidates == []
    assert service.get_active_chunk(candidate.chunk.chunk_id, filters=forbidden) is None
    with pytest.raises(RagRetrievalError, match="scope"):
        service.validate_evidence_candidates(result, filters=forbidden)
    assert service.evidence_cache_version() is None


@pytest.mark.parametrize("fault", ["asset", "source", "generation", "page", "text", "deleted"])
def test_native_visual_evidence_rejects_changed_or_forged_source(published_visual, fault):
    from backend.rag.visual_retrieval import _path_from_file_uri
    service, _, _, manifest, source, _ = published_visual
    result = service.retrieve("blue chart")
    candidate = result.candidates[0]
    if fault == "asset":
        _path_from_file_uri(candidate.chunk.metadata["asset_uri"]).write_bytes(b"changed")
    elif fault == "source":
        source.write_bytes(b"changed")
    elif fault == "generation":
        manifest.record.generation_id = "g2"
    elif fault == "deleted":
        manifest.record = None
    elif fault == "page":
        candidate.chunk.page_number = 9
    else:
        candidate.chunk.text = "invented chart data"
    with pytest.raises(RagRetrievalError):
        service.validate_evidence_candidates(result)


def test_visual_reindex_uses_current_generation_and_failure_keeps_old_points(published_visual, monkeypatch):
    service, coordinator, store, manifest, source, config = published_visual
    old = service.retrieve("blue chart").candidates[0].chunk
    original_upsert = store._client.upsert
    def fail(**kwargs):
        raise RuntimeError("injected upsert failure")
    manifest.record.generation_id = "g2"
    monkeypatch.setattr(store._client, "upsert", fail)
    with pytest.raises(RagVectorStoreError):
        coordinator.ensure_document(source, "doc-1")
    assert store.get_chunk(old.chunk_id, generation_id="g1") == old
    assert service.retrieve("blue chart").candidates == []
    monkeypatch.setattr(store._client, "upsert", original_upsert)
    assert coordinator.ensure_document(source, "doc-1") == 1
    new = service.retrieve("blue chart")
    assert new.candidates[0].index_generation == "g2"
    service.validate_evidence_candidates(new)
    assert store.has_document("doc-1", index_version=visual_retrieval_index_version(config),
        generation_id="g2", content_hash=manifest.record.content_hash)


def test_visual_source_hash_is_checked_before_rendering(published_visual):
    _, _, _, manifest, source, config = published_visual
    source.write_bytes(b"modified PDF")
    with pytest.raises(RagRetrievalError, match="source document changed"):
        build_visual_index_items(source, manifest.record, config)


def test_failed_visual_publication_removes_new_points_and_preserves_old(published_visual, monkeypatch):
    service, coordinator, store, manifest, source, config = published_visual
    old = service.retrieve("blue chart").candidates[0].chunk
    original_publish = store._client.set_payload
    def fail_after_publication(**kwargs):
        original_publish(**kwargs)
        raise RuntimeError("injected publication acknowledgement failure")
    manifest.record.generation_id = "g2"
    monkeypatch.setattr(store._client, "set_payload", fail_after_publication)
    with pytest.raises(RagVectorStoreError):
        coordinator.ensure_document(source, "doc-1")
    assert store.get_chunk(old.chunk_id, generation_id="g1") == old
    assert not store.has_document("doc-1", index_version=visual_retrieval_index_version(config),
        generation_id="g2", content_hash=manifest.record.content_hash)
    assert service.retrieve("blue chart").candidates == []
