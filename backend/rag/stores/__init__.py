from __future__ import annotations

from typing import Any

from backend.rag.config import RagVectorStoreConfig
from backend.rag.exceptions import RagConfigurationError
from backend.rag.stores.base import VectorSearchFilter, VectorStore


def create_vector_store(
    config: RagVectorStoreConfig, *, dimension: int, repository=None, fingerprint=None
):
    if config.provider != "faiss_local":
        raise RagConfigurationError(
            "Run scripts/migration before opening the legacy vector store"
        )
    from backend.rag.stores.faiss import FaissVectorStore

    return FaissVectorStore(
        config, dimension=dimension, repository=repository, fingerprint=fingerprint
    )


def __getattr__(name: str) -> Any:
    if name == "FaissVectorStore":
        from backend.rag.stores.faiss import FaissVectorStore

        return FaissVectorStore
    raise AttributeError(name)


__all__ = [
    "FaissVectorStore",
    "VectorSearchFilter",
    "VectorStore",
    "create_vector_store",
]
