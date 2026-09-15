from __future__ import annotations

from pathlib import Path

import pytest

from backend.rag.config import RagVectorStoreConfig
from backend.rag.exceptions import RagConfigurationError, RagVectorStoreError
from backend.rag.models import DocumentChunk
from backend.rag.stores import QdrantLocalVectorStore, VectorSearchFilter


def make_chunk(
    chunk_id: str,
    *,
    document_id: str = "doc_one",
    text: str = "Gaussian process PID tuning.",
    language: str = "en",
    category: str = "control",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title="Test Paper",
        section_heading="Methods",
        page_number=2,
        chunk_index=0,
        paragraph_index=1,
        start_char=10,
        end_char=10 + len(text),
        token_count=5,
        language=language,
        source_uri="file:///paper.pdf",
        document_hash="hash",
        parser_version="pdf-v1",
        chunker_version="structure-aware-v1",
        embedding_version="qwen3-0.6b",
        metadata={"source_kind": "pdf", "category": category},
    )


def make_store(path: Path, *, dimension: int = 4) -> QdrantLocalVectorStore:
    return QdrantLocalVectorStore(
        RagVectorStoreConfig(storage_path=str(path)),
        dimension=dimension,
    )


def test_create_collection_with_expected_schema(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        store.ensure_collection()
        info = store._client.get_collection(store.collection_name)

        assert info.config.params.vectors.size == 4
        assert info.config.params.vectors.distance.value == "Cosine"
    finally:
        store.close()


def test_upsert_and_dense_search(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        first = make_chunk("chunk_first")
        second = make_chunk(
            "chunk_second",
            document_id="doc_two",
            text="Computer vision paper.",
            category="vision",
        )
        store.upsert_chunks(
            [first, second],
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        )

        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)

        assert [result.chunk.chunk_id for result in results] == [
            "chunk_first",
            "chunk_second",
        ]
        assert results[0].dense_score == pytest.approx(1.0)
        assert [result.rank for result in results] == [1, 2]
    finally:
        store.close()


def test_get_chunk_uses_deterministic_point_identity(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        chunk = make_chunk("chunk_stable")
        store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])

        restored = store.get_chunk("chunk_stable")

        assert restored == chunk
        assert store.get_chunk("chunk_missing") is None
    finally:
        store.close()


def test_search_supports_metadata_filter(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        control = make_chunk("chunk_control", category="control")
        vision = make_chunk(
            "chunk_vision",
            document_id="doc_two",
            category="vision",
        )
        store.upsert_chunks(
            [control, vision],
            [[1.0, 0.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]],
        )

        results = store.search(
            [1.0, 0.0, 0.0, 0.0],
            top_k=5,
            filters=VectorSearchFilter(metadata={"category": "vision"}),
        )

        assert [result.chunk.chunk_id for result in results] == ["chunk_vision"]
    finally:
        store.close()


def test_search_supports_document_and_language_filters(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        english = make_chunk("chunk_en", document_id="doc_en", language="en")
        chinese = make_chunk("chunk_zh", document_id="doc_zh", language="zh")
        store.upsert_chunks(
            [english, chinese],
            [[1.0, 0.0, 0.0, 0.0], [0.9, 0.1, 0.0, 0.0]],
        )

        results = store.search(
            [1.0, 0.0, 0.0, 0.0],
            top_k=5,
            filters=VectorSearchFilter(document_ids=["doc_zh"], language="zh"),
        )

        assert [result.chunk.chunk_id for result in results] == ["chunk_zh"]
    finally:
        store.close()


def test_delete_document_removes_only_matching_chunks(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        first = make_chunk("chunk_one", document_id="doc_one")
        second = make_chunk("chunk_two", document_id="doc_two")
        store.upsert_chunks(
            [first, second],
            [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        )

        store.delete_document("doc_one")

        assert store.get_chunk("chunk_one") is None
        assert store.get_chunk("chunk_two") == second
    finally:
        store.close()


def test_duplicate_upsert_is_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        chunk = make_chunk("chunk_repeat")
        store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])
        store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])

        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=10)

        assert [result.chunk.chunk_id for result in results] == ["chunk_repeat"]
    finally:
        store.close()


def test_persistent_store_can_search_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "qdrant"
    first_store = make_store(path)
    chunk = make_chunk("chunk_persisted")
    first_store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])
    first_store.close()

    second_store = make_store(path)
    try:
        results = second_store.search([1.0, 0.0, 0.0, 0.0], top_k=1)

        assert results[0].chunk == chunk
    finally:
        second_store.close()


def test_wrong_vector_dimension_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        with pytest.raises(RagVectorStoreError, match="dimension mismatch"):
            store.upsert_chunks([make_chunk("chunk_bad")], [[1.0, 0.0]])

        with pytest.raises(RagVectorStoreError, match="dimension mismatch"):
            store.search([1.0, 0.0], top_k=1)
    finally:
        store.close()


def test_wrong_existing_collection_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "qdrant"
    first_store = make_store(path, dimension=3)
    first_store.ensure_collection()
    first_store.close()

    second_store = make_store(path, dimension=4)
    try:
        with pytest.raises(RagConfigurationError, match="schema mismatch"):
            second_store.ensure_collection()
    finally:
        second_store.close()


def test_chunk_vector_count_mismatch_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path / "qdrant")
    try:
        with pytest.raises(RagVectorStoreError, match="count mismatch"):
            store.upsert_chunks([make_chunk("chunk_one")], [])
    finally:
        store.close()
