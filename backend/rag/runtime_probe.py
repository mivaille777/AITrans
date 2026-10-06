"""Offline numerical smoke test shared by source and frozen distributions."""

from tempfile import TemporaryDirectory

from backend.rag.config import RagVectorStoreConfig
from backend.rag.models import DocumentChunk
from backend.rag.stores import create_vector_store
from backend.rag.visual_scoring import maxsim


def probe_local_vector_runtime():
    with TemporaryDirectory(prefix="aitrans-faiss-probe-") as root:
        config = RagVectorStoreConfig(storage_path=root)
        chunk = DocumentChunk(chunk_id="probe", document_id="probe", text="probe", chunk_index=0)
        store = create_vector_store(config, dimension=2)
        try:
            store.upsert_chunks([chunk], [[1.0, 0.0]])
            assert store.search([1.0, 0.0], top_k=3)[0].chunk == chunk
            device = store._index.diagnostics()
        finally:
            store.close()
        store = create_vector_store(config, dimension=2)
        try:
            assert store.search([1.0, 0.0], top_k=1)[0].dense_score == 1.0
        finally:
            store.close()
        assert maxsim([[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0], [0.0, 1.0]]) == 2.0
    return {"add_search": True, "sqlite_reopen": True, "maxsim": True, "faiss": device}
