from typing import Protocol, runtime_checkable

from backend.rag.models import RetrievalCandidate


@runtime_checkable
class RerankerProvider(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_k: int,
    ) -> list[RetrievalCandidate]: ...


__all__ = ["RerankerProvider"]
