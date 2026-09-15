from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.rag.stores.base import VectorSearchFilter, VectorStore

if TYPE_CHECKING:
    from backend.rag.stores.qdrant import QdrantLocalVectorStore


def __getattr__(name: str) -> Any:
    if name == "QdrantLocalVectorStore":
        from backend.rag.stores.qdrant import QdrantLocalVectorStore

        return QdrantLocalVectorStore
    raise AttributeError(name)


__all__ = ["QdrantLocalVectorStore", "VectorSearchFilter", "VectorStore"]
