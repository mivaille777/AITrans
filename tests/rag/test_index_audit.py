from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from backend.rag.config import RagVectorStoreConfig
from backend.rag.index_audit import IndexAuditError, audit_index_consistency
from backend.rag.index_manifest import IndexManifest, ready_manifest_record
from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores import QdrantLocalVectorStore


def _chunk(
    chunk_id: str,
    document_id: str = "doc_one",
    *,
    generation: str = "",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text="Source grounded retrieval evidence.",
        chunk_index=0,
        metadata={"index_generation": generation} if generation else {},
    )


def _ready_record(document_id: str, chunk_ids: list[str]):
    return ready_manifest_record(
        document_id=document_id,
        content_hash=sha256(document_id.encode()).hexdigest(),
        source_uri=f"file:///{document_id}.txt",
        title=document_id,
        parser_version="test-parser-v1",
        chunker_version="test-chunker-v1",
        embedding_model="test-embedding-v1",
        embedding_dimension=4,
        chunk_ids=chunk_ids,
    )


def _vector_store(path: Path) -> QdrantLocalVectorStore:
    return QdrantLocalVectorStore(
        RagVectorStoreConfig(storage_path=str(path), collection_name="audit_test"),
        dimension=4,
    )


def _write_vector_chunks(
    store: QdrantLocalVectorStore,
    chunks: list[DocumentChunk],
) -> None:
    store.upsert_chunks(chunks, [[1.0, 0.0, 0.0, 0.0] for _ in chunks])


def test_audit_reports_cross_store_chunk_and_generation_differences_read_only(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    sparse_path = tmp_path / "bm25.json"
    manifest = IndexManifest(manifest_path)
    manifest.upsert(_ready_record("doc_one", ["chunk_shared"]))
    sparse = BM25SparseRetriever(sparse_path)
    sparse.index_chunks(
        [
            _chunk("chunk_shared", generation="generation-a"),
            _chunk("chunk_sparse_only", generation="generation-a"),
        ]
    )
    vector = _vector_store(tmp_path / "qdrant")
    _write_vector_chunks(
        vector,
        [
            _chunk("chunk_shared", generation="generation-b"),
            _chunk("chunk_vector_only", generation="generation-b"),
        ],
    )
    try:
        manifest_before = manifest_path.read_bytes()
        sparse_before = sparse_path.read_bytes()
        vector_before = [
            vector.get_chunk("chunk_shared"),
            vector.get_chunk("chunk_vector_only"),
        ]

        report = audit_index_consistency(
            manifest=manifest,
            sparse_retriever=sparse,
            vector_store=vector,
        )

        assert report.status == "divergent"
        assert report.chunk_ids_equal is False
        assert report.document_ids_equal is True
        assert report.generation_status == "divergent"
        document = report.documents[0]
        assert document.missing_chunk_ids["manifest"] == [
            "chunk_sparse_only",
            "chunk_vector_only",
        ]
        assert document.missing_chunk_ids["bm25"] == ["chunk_vector_only"]
        assert document.missing_chunk_ids["qdrant"] == ["chunk_sparse_only"]
        assert document.generation_mismatch_chunk_ids == ["chunk_shared"]
        assert manifest_path.read_bytes() == manifest_before
        assert sparse_path.read_bytes() == sparse_before
        assert [
            vector.get_chunk("chunk_shared"),
            vector.get_chunk("chunk_vector_only"),
        ] == vector_before
    finally:
        vector.close()


def test_audit_reports_document_ids_missing_from_a_store(tmp_path: Path) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(_ready_record("doc_manifest", ["chunk_manifest"]))
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    sparse.index_chunks([_chunk("chunk_sparse", document_id="doc_sparse")])
    vector = _vector_store(tmp_path / "qdrant")
    _write_vector_chunks(vector, [_chunk("chunk_vector", document_id="doc_vector")])
    try:
        report = audit_index_consistency(
            manifest=manifest,
            sparse_retriever=sparse,
            vector_store=vector,
        )

        assert report.document_ids_equal is False
        assert report.status == "divergent"
        assert {
            finding.code
            for finding in report.findings
            if finding.code == "DOCUMENT_ID_DIFFERENCE"
        }
    finally:
        vector.close()


def test_matching_legacy_catalogues_are_incomplete_without_generation_metadata(
    tmp_path: Path,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    manifest.upsert(_ready_record("doc_one", ["chunk_shared"]))
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    sparse.index_chunks([_chunk("chunk_shared")])
    vector = _vector_store(tmp_path / "qdrant")
    _write_vector_chunks(vector, [_chunk("chunk_shared")])
    try:
        report = audit_index_consistency(
            manifest=manifest,
            sparse_retriever=sparse,
            vector_store=vector,
        )

        assert report.chunk_ids_equal is True
        assert report.document_ids_equal is True
        assert report.generation_status == "unavailable"
        assert report.status == "incomplete"
        assert "GENERATION_METADATA_UNAVAILABLE" in {
            finding.code for finding in report.findings
        }
    finally:
        vector.close()


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("manifest", "manifest"),
        ("sparse_retriever", "BM25"),
        ("vector_store", "Qdrant"),
    ],
)
def test_missing_required_catalogue_fails_explicitly(
    tmp_path: Path,
    missing: str,
    message: str,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    vector = _vector_store(tmp_path / "qdrant")
    inputs = {
        "manifest": manifest,
        "sparse_retriever": sparse,
        "vector_store": vector,
    }
    inputs[missing] = None
    try:
        with pytest.raises(IndexAuditError, match=message):
            audit_index_consistency(**inputs)
    finally:
        vector.close()


def test_missing_qdrant_collection_is_reported_without_creating_it(
    tmp_path: Path,
) -> None:
    manifest = IndexManifest(tmp_path / "manifest.json")
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    vector = _vector_store(tmp_path / "qdrant")
    try:
        with pytest.raises(IndexAuditError, match="collection .* is missing"):
            audit_index_consistency(
                manifest=manifest,
                sparse_retriever=sparse,
                vector_store=vector,
            )
        assert vector._client.collection_exists(vector.collection_name) is False
    finally:
        vector.close()
