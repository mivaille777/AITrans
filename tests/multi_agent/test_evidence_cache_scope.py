from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.orchestration.evidence_service import (
    ScopedEvidenceCache,
    ScopedEvidenceService,
)
from backend.models.agent_tasks import ScopeContext
from backend.rag.config import RagRetrievalConfig, RagVectorStoreConfig
from backend.rag.embeddings.base import EmbeddingFingerprint
from backend.rag.exceptions import RagRetrievalError
from backend.rag.index_manifest import IndexManifest, ready_manifest_record
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse.store import BM25SparseRetriever
from backend.rag.stores import FaissVectorStore


class CountingRag:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def retrieve(self, query: str, *, filters, final_top_k: int):
        del final_top_k
        document_id = filters.document_ids[0]
        self.calls.append(tuple(filters.document_ids))
        chunk = DocumentChunk(
            chunk_id=f"chunk-{document_id}",
            document_id=document_id,
            text=f"{query} from {document_id}",
            chunk_index=0,
            document_hash=f"hash-{document_id}",
        )
        return RetrievalResult(
            query=query,
            candidates=[RetrievalCandidate(chunk=chunk, fusion_score=0.8, rank=1)],
        )


def _scope(document_id: str, revision: str, version: str) -> ScopeContext:
    return ScopeContext.issue(
        scope_revision=revision,
        allowed_document_ids=[document_id],
        source_versions={document_id: version},
    )


def test_cache_deduplicates_same_scope_query_and_source_version() -> None:
    rag = CountingRag()
    service = ScopedEvidenceService(rag_retriever=rag, cache=ScopedEvidenceCache())
    scope = _scope("doc-a", "scope-a-r1", "v1")

    first = service.retrieve_packets(query="accuracy", scope=scope)
    second = service.retrieve_packets(query="accuracy", scope=scope)

    assert rag.calls == [("doc-a",)]
    assert first == second
    assert first is not second


def test_cache_hit_has_current_trace_and_links_original_inference(live_evidence):
    from backend.rag.observability import bind_rag_trace

    service, rag, _, _, _, publish = live_evidence
    publish("doc-a", "g1", "accuracy is 95 percent")
    scope = _scope("doc-a", "scope-r1", "v1")
    first_events, second_events = [], []
    with bind_rag_trace("request-a", lambda kind, payload: first_events.append((kind, payload))):
        first = service.retrieve_packets(query="accuracy", scope=scope)
    with bind_rag_trace("request-b", lambda kind, payload: second_events.append((kind, payload))):
        second = service.retrieve_packets(query="accuracy", scope=scope)
    assert rag.calls == 1
    assert first[0].text == second[0].text
    assert first[0].metadata["retrieval_span"]["trace_id"] == "request-a"
    assert second[0].metadata["retrieval_span"]["trace_id"] == "request-b"
    assert second[0].metadata["evidence_cache_hit"] is True
    assert second[0].metadata["cache_source_span_ids"] == [first[0].metadata["retrieval_span"]["span_id"]]
    assert set(second[0].metadata["stage_timings"]) == {"cache"}
    assert all(payload["trace_id"] == "request-b" for _, payload in second_events)
    selected = next(payload for kind, payload in second_events if kind.value == "rag_evidence_selected")
    assert [span["stage"] for span in selected["spans"]] == ["cache"]
    assert selected["started_at"] >= first[0].metadata["retrieval_span"]["ended_at"]


def test_cache_does_not_cross_scope_revision_document_or_source_version() -> None:
    rag = CountingRag()
    service = ScopedEvidenceService(rag_retriever=rag, cache=ScopedEvidenceCache())

    service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "scope-a-r1", "v1"))
    service.retrieve_packets(query="accuracy", scope=_scope("doc-b", "scope-b-r1", "v1"))
    service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "scope-a-r2", "v2"))

    assert rag.calls == [("doc-a",), ("doc-b",), ("doc-a",)]


def test_cache_uses_actual_document_selection_even_when_scope_ref_is_retained():
    rag = CountingRag()
    service = ScopedEvidenceService(rag_retriever=rag)
    original = _scope("doc-a", "scope-r1", "v1")
    narrowed = original.model_copy(update={"allowed_document_ids": ["doc-b"]})
    service.retrieve_packets(query="accuracy", scope=original)
    packets = service.retrieve_packets(query="accuracy", scope=narrowed)
    assert [packet.evidence_ref.source_id for packet in packets] == ["doc-b"]
    assert rag.calls == [("doc-a",), ("doc-b",)]


@pytest.fixture
def live_evidence(tmp_path):
    class Embedding:
        model_name = "test-model"
        dimension = 4
        fingerprint = EmbeddingFingerprint(
            model_id="test-model", dimension=4, normalized=True,
            query_prefix="", document_prefix="", model_revision="v1",
        )

        def embed_query(self, query):
            return [1.0, 0.0, 0.0, 0.0]

    class CountingRetrieval(RetrievalService):
        calls = 0

        def retrieve(self, *args, **kwargs):
            self.calls += 1
            return super().retrieve(*args, **kwargs)

    vector = FaissVectorStore(
        RagVectorStoreConfig(storage_path=str(tmp_path / "faiss")), dimension=4,
    )
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    manifest = IndexManifest(tmp_path / "manifest.json")
    rag = CountingRetrieval(
        embedding_provider=Embedding(), vector_store=vector, sparse_retriever=sparse,
        manifest=manifest, config=RagRetrievalConfig(small_to_big_enabled=False),
    )

    def publish(document_id, generation, text):
        chunk = DocumentChunk(
            chunk_id=f"chunk-{document_id}-{generation}", document_id=document_id,
            chunk_index=0, text=text, document_hash=generation,
        )
        manifest.begin_generation(document_id, generation, [chunk.chunk_id])
        vector.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]], generation_id=generation)
        sparse.index_chunks([chunk], generation_id=generation)
        manifest.validate_generation(document_id, generation, [chunk.chunk_id])
        record = ready_manifest_record(
            document_id=document_id, content_hash=generation, source_uri="",
            title=document_id, parser_version="test-parser", chunker_version="test-chunker",
            embedding_model="test-model", embedding_dimension=4,
            embedding_fingerprint=rag._embedding.fingerprint, chunk_ids=[chunk.chunk_id],
        ).model_copy(update={"generation_id": generation})
        manifest.publish_generation(document_id, generation, manifest_record=record)
        return chunk

    try:
        yield ScopedEvidenceService(rag_retriever=rag), rag, vector, sparse, manifest, publish
    finally:
        vector.close()


def test_live_cache_tracks_publication_deletion_and_empty_to_ready(live_evidence):
    service, rag, vector, sparse, manifest, publish = live_evidence
    scope = _scope("doc-a", "scope-r1", "snapshot-v1")
    assert service.retrieve_packets(query="accuracy", scope=scope) == ()
    publish("doc-a", "g1", "accuracy old evidence")
    first = service.retrieve_packets(query="accuracy", scope=scope)
    assert [packet.text for packet in first] == ["accuracy old evidence"]
    assert service.retrieve_packets(query="accuracy", scope=scope) == first
    assert rag.calls == 2
    publish("doc-a", "g2", "accuracy new evidence")
    assert [packet.text for packet in service.retrieve_packets(query="accuracy", scope=scope)] == [
        "accuracy new evidence",
    ]
    vector.delete_document("doc-a")
    sparse.delete_document("doc-a")
    manifest.delete("doc-a")
    assert service.retrieve_packets(query="accuracy", scope=scope) == ()
    assert rag.calls == 3  # The original empty publication snapshot is reusable.


def test_cached_document_is_rechecked_when_source_chunk_disappears(live_evidence):
    service, rag, vector, _, _, publish = live_evidence
    publish("doc-a", "g1", "accuracy evidence")
    scope = _scope("doc-a", "scope-r1", "v1")
    assert service.retrieve_packets(query="accuracy", scope=scope)
    vector.delete_document("doc-a")
    with pytest.raises(RagRetrievalError, match="source chunk is missing"):
        service.retrieve_packets(query="accuracy", scope=scope)
    assert rag.calls == 2


def test_cold_document_evidence_runs_current_publication_validation(live_evidence, monkeypatch):
    service, rag, _, _, _, publish = live_evidence
    old = publish("doc-a", "g1", "accuracy old evidence")
    publish("doc-a", "g2", "accuracy new evidence")
    monkeypatch.setattr(rag, "retrieve", lambda *args, **kwargs: RetrievalResult(
        query="accuracy", candidates=[RetrievalCandidate(chunk=old, index_generation="g1")],
    ))
    with pytest.raises(RagRetrievalError, match="active generation"):
        service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "r1", "v1"))


def test_mutable_note_content_is_not_reused_from_packet_cache():
    note = SimpleNamespace(
        note_id="note-a", fingerprint="v1", source_text="accuracy old note",
        translated_text="", ai_content="", user_note="", resource_url="",
        section_heading="", display_title="Note A",
    )
    notes = SimpleNamespace(search=lambda *args, **kwargs: [SimpleNamespace(note=note, score=1.0)])
    service = ScopedEvidenceService(research_notes=notes)
    scope = ScopeContext.issue(scope_revision="r1", allowed_note_ids=["note-a"])
    assert service.retrieve_packets(query="accuracy", scope=scope)[0].text == "accuracy old note"
    note.source_text = "accuracy updated note"
    note.fingerprint = "v2"
    updated = service.retrieve_packets(query="accuracy", scope=scope)[0]
    assert updated.text == "accuracy updated note"
    assert updated.evidence_ref.source_hash == "v2"


def test_evidence_cache_is_bounded_and_keeps_deep_copy_isolation():
    cache = ScopedEvidenceCache(max_entries=2)
    service = ScopedEvidenceService(rag_retriever=CountingRag())
    packets = service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "r1", "v1"))
    cache.put("a", packets)
    cache.put("b", packets)
    cache.get("a")[0].text = "changed by caller"
    cache.put("c", packets)
    assert cache.get("b") is None
    assert cache.get("a")[0].text == packets[0].text


def test_live_cache_rechecks_global_import_and_embedding_model_version(live_evidence):
    service, rag, _, _, _, publish = live_evidence
    scope = ScopeContext.issue(scope_revision="global")
    assert service.retrieve_packets(query="accuracy", scope=scope) == ()
    publish("doc-a", "g1", "accuracy evidence")
    assert [packet.evidence_ref.source_id for packet in service.retrieve_packets(query="accuracy", scope=scope)] == [
        "doc-a",
    ]
    publish("doc-b", "g2", "accuracy more evidence")
    assert {packet.evidence_ref.source_id for packet in service.retrieve_packets(query="accuracy", scope=scope)} == {
        "doc-a", "doc-b",
    }
    rag._embedding.fingerprint = EmbeddingFingerprint(
        model_id="test-model", dimension=4, normalized=True,
        query_prefix="", document_prefix="", model_revision="v2",
    )
    changed_model = service.retrieve_packets(query="accuracy", scope=scope)
    assert all(packet.metadata["retrieval_strategy"] == "sparse-only" for packet in changed_model)
    assert rag.calls == 4
    assert service.retrieve_packets(query="accuracy", scope=scope) == changed_model
    assert rag.calls == 4


def test_empty_cache_hit_cannot_hide_publication_during_cache_lookup(live_evidence, monkeypatch):
    service, rag, _, _, _, publish = live_evidence
    scope = _scope("doc-a", "r1", "v1")
    assert service.retrieve_packets(query="accuracy", scope=scope) == ()
    original = rag.evidence_cache_version
    switched = False

    def publish_after_version_read(*, filters):
        nonlocal switched
        version = original(filters=filters)
        if not switched:
            switched = True
            publish("doc-a", "g1", "accuracy published evidence")
        return version

    monkeypatch.setattr(rag, "evidence_cache_version", publish_after_version_read)
    assert service.retrieve_packets(query="accuracy", scope=scope)[0].text == "accuracy published evidence"
    assert rag.calls == 2
