from backend.rag.sparse import BM25SparseRetriever
from tests.rag.test_faiss_store import make_store
from tests.rag.test_index_service import make_service


def test_ready_manifest_cannot_reuse_missing_dense_or_sparse(tmp_path):
    source = tmp_path / "paper.txt"
    source.write_text("Persistent text about Gaussian processes.", encoding="utf-8")
    store = make_store(tmp_path / "faiss")
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    service, _parser, _embedding, _, manifest = make_service(tmp_path, store=store)
    service._sparse_retriever = sparse
    try:
        first = service.index_document(source)
        assert first.status.value == "ready"
        assert service.index_document(source).reused_existing
        record = manifest.get(first.document_id)
        store.delete_chunks(record.chunk_ids, generation_id=record.generation_id)
        repaired = service.index_document(source)
        assert repaired.status.value == "ready" and not repaired.reused_existing
        record = manifest.get(first.document_id)
        sparse.delete_document(first.document_id, generation_id=record.generation_id)
        repaired = service.index_document(source)
        assert repaired.status.value == "ready" and not repaired.reused_existing
    finally:
        store.close()
