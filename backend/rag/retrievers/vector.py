from __future__ import annotations

from backend.rag.models import RetrievalCandidate
from backend.rag.retrievers.base import RetrievalRequest, record_channel_hits
from backend.rag.stores.base import VectorStore


class VectorRetriever:
    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def retrieve(self, request: RetrievalRequest) -> list[RetrievalCandidate]:
        if request.allowed_document_ids == ():
            return []
        if request.query_vector is None:
            raise ValueError("vector channel requires a query embedding")
        kwargs = {"top_k": request.top_k, "filters": request.search_filters()}
        if request.active_generations is not None:
            kwargs["active_generations"] = dict(request.active_generations)
        candidates = self._store.search(list(request.query_vector), **kwargs)
        return record_channel_hits(
            request, candidates, channel="vector", score_field="dense_score"
        )
