from __future__ import annotations

from backend.rag.models import RetrievalCandidate
from backend.rag.retrievers.base import RetrievalRequest, record_channel_hits
from backend.rag.sparse.store import SparseRetriever


class BM25Retriever:
    def __init__(self, store: SparseRetriever) -> None:
        self._store = store

    def retrieve(self, request: RetrievalRequest) -> list[RetrievalCandidate]:
        if request.allowed_document_ids == ():
            return []
        kwargs = {}
        if request.active_generations is not None:
            kwargs["active_generations"] = dict(request.active_generations)
        candidates = self._store.search(
            request.query, request.top_k, request.search_filters(), **kwargs
        )
        return record_channel_hits(
            request, candidates, channel="bm25", score_field="sparse_score"
        )
