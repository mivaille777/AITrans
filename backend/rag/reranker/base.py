from __future__ import annotations

from typing import Protocol


class RerankerProvider(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        ...


__all__ = ["RerankerProvider"]
