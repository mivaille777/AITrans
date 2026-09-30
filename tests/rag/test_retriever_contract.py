from __future__ import annotations

import pytest

from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.retrievers.base import RetrievalRequest, RetrieverChannel
from backend.rag.retrievers.bm25 import BM25Retriever
from backend.rag.retrievers.vector import VectorRetriever
from backend.rag.stores.base import VectorSearchFilter


def candidate(document_id="allowed", generation="ready", rank=2):
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=f"{document_id}-{generation}",
            document_id=document_id,
            text="evidence",
            chunk_index=0,
            metadata={"index_generation": generation},
        ),
        dense_score=0.8,
        sparse_score=3.0,
        rank=rank,
    )


class Store:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, top_k, filters=None, **kwargs):
        self.calls.append((query, top_k, filters.model_copy(deep=True), kwargs))
        filters.document_ids.clear()
        return self.results


def test_channels_share_frozen_scope_and_preserve_original_scores():
    filters = VectorSearchFilter(document_ids=["allowed", "forbidden"], language="en")
    generations = {"allowed": "ready"}
    request = RetrievalRequest(
        query="query",
        top_k=5,
        filters=filters,
        allowed_document_ids=("allowed",),
        active_generations=generations,
        query_vector=(1.0, 0.0),
        trace_id="trace",
    )
    filters.document_ids[:] = ["forbidden"]
    generations["allowed"] = "stale"
    results = [candidate("forbidden"), candidate(generation="stale"), candidate()]
    vector, sparse = Store(results), Store(results)
    channels = [VectorRetriever(vector), BM25Retriever(sparse)]

    for channel, name, score in zip(
        channels, ("vector", "bm25"), (0.8, 3.0), strict=True
    ):
        assert isinstance(channel, RetrieverChannel)
        hits = channel.retrieve(request)
        assert len(hits) == 1
        assert hits[0].index_generation == "ready"
        assert hits[0].trace_id == "trace"
        assert hits[0].channel_hits[0].model_dump() == {
            "channel": name,
            "raw_score": score,
            "rank": 2,
        }
    for store in (vector, sparse):
        assert store.calls[0][2].document_ids == ["allowed"]
        assert store.calls[0][2].language == "en"
        assert store.calls[0][3]["active_generations"] == {"allowed": "ready"}
    assert results[-1].channel_hits == []


@pytest.mark.parametrize("scope", [(), ("other",)])
@pytest.mark.parametrize("channel_type", [VectorRetriever, BM25Retriever])
def test_empty_or_disjoint_scope_does_not_search(scope, channel_type):
    store = Store([candidate()])
    request = RetrievalRequest(
        query="query",
        top_k=5,
        filters=VectorSearchFilter(document_ids=["allowed"]),
        allowed_document_ids=scope,
        query_vector=(1.0, 0.0),
    )

    assert channel_type(store).retrieve(request) == []
    assert store.calls == []


@pytest.mark.parametrize("channel_type", [VectorRetriever, BM25Retriever])
def test_channel_errors_propagate_to_existing_service_fallback(channel_type):
    class FailedStore:
        def search(self, *args, **kwargs):
            raise RuntimeError("store unavailable")

    with pytest.raises(RuntimeError, match="store unavailable"):
        channel_type(FailedStore()).retrieve(
            RetrievalRequest(query="query", top_k=5, query_vector=(1.0, 0.0))
        )


@pytest.mark.parametrize("channel_type", [VectorRetriever, BM25Retriever])
def test_legacy_unscoped_store_requires_no_new_keyword(channel_type):
    class LegacyStore:
        def search(self, query, top_k, filters=None):
            return [candidate(generation=None)]

    hits = channel_type(LegacyStore()).retrieve(
        RetrievalRequest(query="query", top_k=5, query_vector=(1.0, 0.0))
    )
    assert len(hits) == 1
    assert hits[0].index_generation is None


@pytest.mark.parametrize("channel_type", [VectorRetriever, BM25Retriever])
def test_conflicting_generation_cannot_relabel_stale_evidence(channel_type):
    stale = candidate(generation="stale").model_copy(
        update={"index_generation": "ready"}
    )
    with pytest.raises(ValueError, match="generation disagrees"):
        channel_type(Store([stale])).retrieve(
            RetrievalRequest(
                query="query",
                top_k=5,
                active_generations={"allowed": "ready"},
                query_vector=(1.0, 0.0),
            )
        )
