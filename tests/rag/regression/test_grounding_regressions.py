from importlib import import_module
from types import SimpleNamespace

import pytest

from backend.rag.config import RagRetrievalConfig, RagVisualRetrievalConfig
from backend.rag.exceptions import RagRetrievalError
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.retrieval_service import RetrievalService
from backend.rag.source_span import SourceSpan
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.visual_retrieval import VisualRetrievalService
from backend.services.companion_chat_service import CompanionChatService


def test_publication_changed_after_retrieval_cannot_become_a_citation():
    service = RetrievalService(embedding_provider=SimpleNamespace(), vector_store=SimpleNamespace(),
                               sparse_retriever=SimpleNamespace(), manifest=SimpleNamespace(list_active_generations=lambda: {"d": "new"}))
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(
        chunk=DocumentChunk(chunk_id="c", document_id="d", chunk_index=0, text="Old version", metadata={"index_generation": "old"}),
        index_generation="old",
    )])
    with pytest.raises(RagRetrievalError, match="active generation"):
        service.validate_evidence_candidates(result, filters=VectorSearchFilter(document_ids=["d"]))


def test_selected_document_retrieval_failure_refuses_without_llm():
    service = CompanionChatService(retrieval_service=None, retrieval_service_factory=lambda: None, rag_rewrite_enabled=False)
    prepared = service.prepare_execution(query="Summarize this paper", knowledge_enabled=True, document_ids=("d",))
    assert prepared.direct_output_text
    assert not prepared.grounding.citations


def test_missing_source_cannot_become_a_citation():
    service = RetrievalService(embedding_provider=SimpleNamespace(),
                               vector_store=SimpleNamespace(get_chunk=lambda *args, **kwargs: None),
                               sparse_retriever=SimpleNamespace(), manifest=SimpleNamespace(list_active_generations=lambda: {"d": "g"}))
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(
        chunk=DocumentChunk(chunk_id="missing", document_id="d", chunk_index=0, text="invented", metadata={"index_generation": "g"}),
        index_generation="g",
    )])
    with pytest.raises(RagRetrievalError, match="source chunk is missing"):
        service.validate_evidence_candidates(result)


def test_agent_lazy_adapter_preserves_late_validation(monkeypatch):
    from backend.api import agent_dependencies

    calls = []
    monkeypatch.setattr(agent_dependencies, "get_retrieval_service", lambda: SimpleNamespace(
        validate_evidence_candidates=lambda *args, **kwargs: calls.append((args, kwargs)),
    ))
    result = RetrievalResult(query="q")
    agent_dependencies._LazyRetrievalService.validate_evidence_candidates(result)
    assert calls == [((result,), {})]


@pytest.mark.parametrize("module_name", ["backend.api.agent_dependencies", "backend.agent_graph.studio"])
def test_runtime_and_studio_adapters_forward_validation_and_cache_version(monkeypatch, module_name):
    module = import_module(module_name)
    filters = VectorSearchFilter(document_ids=["d"])
    calls = []
    monkeypatch.setattr(module, "get_retrieval_service", lambda: SimpleNamespace(
        validate_evidence_candidates=lambda *args, **kwargs: calls.append((args, kwargs)),
        evidence_cache_version=lambda *, filters: "current-version:" + filters.document_ids[0],
    ))
    result = RetrievalResult(query="q")
    module._LazyRetrievalService.validate_evidence_candidates(result, filters=filters)
    assert calls == [((result,), {"filters": filters})]
    assert module._LazyRetrievalService.evidence_cache_version(filters=filters) == "current-version:d"


@pytest.mark.parametrize("module_name", ["backend.api.agent_dependencies", "backend.agent_graph.studio"])
def test_unversioned_native_visual_wrapper_is_not_cached_or_silently_trusted(monkeypatch, module_name):
    module = import_module(module_name)
    wrapper = VisualRetrievalService(
        base=SimpleNamespace(), provider=SimpleNamespace(), store=SimpleNamespace(),
        config=RagVisualRetrievalConfig(), default_final_top_k=5,
    )
    monkeypatch.setattr(module, "get_retrieval_service", lambda: wrapper)
    assert module._LazyRetrievalService.evidence_cache_version() is None
    with pytest.raises(RagRetrievalError, match="does not support evidence source validation"):
        module._LazyRetrievalService.validate_evidence_candidates(RetrievalResult(query="q"))


def test_deadline_rejects_late_sparse_response_and_all_channels_fail(monkeypatch):
    now = [0]
    def search(*args, **kwargs):
        now[0] = 2
        return [RetrievalCandidate(chunk=DocumentChunk(chunk_id="c", document_id="d", chunk_index=0, text="late"))]
    monkeypatch.setattr("backend.rag.retrieval_service.perf_counter", lambda: now[0])
    service = RetrievalService(embedding_provider=SimpleNamespace(), vector_store=SimpleNamespace(),
                               sparse_retriever=SimpleNamespace(search=search),
                               config=RagRetrievalConfig(channel_deadline_ms=1))
    with pytest.raises(RagRetrievalError, match="deadline"):
        service.retrieve("q", dense_enabled=False)


def _source_validation_service(chunk):
    return RetrievalService(
        embedding_provider=SimpleNamespace(),
        vector_store=SimpleNamespace(get_chunk=lambda *args, **kwargs: chunk),
        sparse_retriever=SimpleNamespace(),
        manifest=SimpleNamespace(list_active_generations=lambda: {"d": "g"}),
    )


def _source_chunk(*, anchored):
    text = "Alpha evidence. Beta result."
    return DocumentChunk(
        chunk_id="c", document_id="d", chunk_index=0, text=text,
        start_char=0, end_char=len(text), document_hash="hash-d",
        source_uri="file:///d.pdf", page_number=2,
        source_span=SourceSpan.from_text(
            text, start_char=0, end_char=len(text), document_hash="hash-d",
            source_uri="file:///d.pdf", page_start=2, page_end=2,
        ) if anchored else None,
        metadata={"index_generation": "g"},
    )


@pytest.mark.parametrize("update", [
    {"text": "Invented evidence"}, {"document_hash": "wrong-hash"},
    {"source_uri": "file:///wrong.pdf"}, {"page_number": 9},
    {"start_char": 99, "end_char": 100},
])
def test_legacy_evidence_must_match_stored_content_and_locator(update):
    stored = _source_chunk(anchored=False)
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(
        chunk=stored.model_copy(update=update), index_generation="g",
    )])
    with pytest.raises(RagRetrievalError, match="source"):
        _source_validation_service(stored).validate_evidence_candidates(result)


@pytest.mark.parametrize("anchored", [False, True])
def test_exact_source_and_checked_excerpt_remain_valid(anchored):
    stored = _source_chunk(anchored=anchored)
    selected_text = "Beta result."
    offset = stored.text.index(selected_text)
    excerpt = stored.model_copy(update={
        "text": selected_text, "start_char": offset, "end_char": len(stored.text),
        "source_span": SourceSpan.from_text(
            stored.text, start_char=offset, end_char=len(stored.text),
            document_hash="hash-d", source_uri="file:///d.pdf", page_start=2, page_end=2,
        ) if anchored else None,
    })
    service = _source_validation_service(stored)
    for chunk in (stored, excerpt):
        service.validate_evidence_candidates(RetrievalResult(
            query="q", candidates=[RetrievalCandidate(chunk=chunk, index_generation="g")],
        ))


@pytest.mark.parametrize("fault", ["missing_span", "quote_hash", "page", "uri"])
def test_anchored_evidence_cannot_drop_or_forge_source_span(fault):
    stored = _source_chunk(anchored=True)
    update = {
        "quote_hash": {"quote_hash": "0" * 64},
        "page": {"page_start": 9, "page_end": 9},
        "uri": {"source_uri": "file:///wrong.pdf"},
    }
    span = None if fault == "missing_span" else stored.source_span.model_copy(update=update[fault])
    chunk_update = {"source_span": span}
    if fault == "uri":
        chunk_update["source_uri"] = span.source_uri
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(
        chunk=stored.model_copy(update=chunk_update), index_generation="g",
    )])
    with pytest.raises(RagRetrievalError, match="source"):
        _source_validation_service(stored).validate_evidence_candidates(result)


@pytest.mark.parametrize("field", ["start_char", "end_char"])
def test_mutated_chunk_offsets_cannot_disagree_with_its_source_span(field):
    stored = _source_chunk(anchored=True)
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(
        chunk=stored.model_copy(deep=True), index_generation="g",
    )])
    setattr(result.candidates[0].chunk, field, 999)
    with pytest.raises(RagRetrievalError, match="source"):
        _source_validation_service(stored).validate_evidence_candidates(result)


def test_publication_switch_during_source_validation_rejects_the_old_result():
    stored = _source_chunk(anchored=False)
    active = {"d": "g"}
    service = _source_validation_service(stored)
    service._manifest.list_active_generations = lambda: dict(active)

    def read_then_publish(*args, **kwargs):
        active["d"] = "new"
        return stored

    service._vector_store.get_chunk = read_then_publish
    result = RetrievalResult(query="q", candidates=[RetrievalCandidate(chunk=stored, index_generation="g")])
    with pytest.raises(RagRetrievalError, match="active generation"):
        service.validate_evidence_candidates(result)
