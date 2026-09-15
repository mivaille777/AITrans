from __future__ import annotations

from pathlib import Path

from backend.rag.config import RagVectorStoreConfig
from backend.rag.stores import QdrantLocalVectorStore, VectorStore


def test_qdrant_store_satisfies_vector_store_protocol(tmp_path: Path) -> None:
    store = QdrantLocalVectorStore(
        RagVectorStoreConfig(storage_path=str(tmp_path / "qdrant")),
        dimension=4,
    )
    try:
        assert isinstance(store, VectorStore)
        assert store.dimension == 4
        assert store.collection_name == "aitrans_knowledge"
    finally:
        store.close()
