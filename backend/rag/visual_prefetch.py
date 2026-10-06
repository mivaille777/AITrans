"""Visual prefetch factory and model-independent pooling."""
from __future__ import annotations

from backend.rag.config import RagVisualRetrievalConfig
from backend.rag.stores.local_repository import LocalVectorRepository
from backend.rag.visual_scoring import pool_multivector


def create_visual_vector_store(config: RagVisualRetrievalConfig, *, repository: LocalVectorRepository | None = None):
    from backend.rag.stores.faiss_visual import FaissVisualMultiVectorStore
    from backend.rag.visual_adaptive import AdaptivePrefetchPolicy
    return FaissVisualMultiVectorStore(config, repository=repository, policy=AdaptivePrefetchPolicy(enabled=False))

__all__ = ["create_visual_vector_store", "pool_multivector"]
