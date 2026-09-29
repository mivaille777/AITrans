from __future__ import annotations

from pathlib import Path

from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever


def _chunk(
    chunk_id: str,
    text: str,
    *,
    generation_id: str | None = None,
    chunk_index: int = 0,
) -> DocumentChunk:
    metadata = {"index_generation": generation_id} if generation_id else {}
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc_one",
        text=text,
        chunk_index=chunk_index,
        section_path=["Methods"],
        metadata=metadata,
    )


def test_generations_coexist_are_queryable_and_delete_independently(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bm25.json"
    retriever = BM25SparseRetriever(path)
    legacy = _chunk("chunk_shared", "legacy blue harbor evidence")
    generation_one = _chunk(
        "chunk_shared",
        "generation one amber evidence",
        generation_id="generation-one",
    )
    generation_two = _chunk(
        "chunk_shared",
        "generation two violet evidence",
        generation_id="generation-two",
    )

    retriever.index_chunks([legacy])
    retriever.index_chunks([generation_one], generation_id="generation-one")
    retriever.index_chunks([generation_two], generation_id="generation-two")

    assert len(retriever.list_chunks()) == 3
    assert [item.chunk.text for item in retriever.search("blue harbor", 5)] == [
        legacy.text
    ]
    assert [
        item.chunk.text
        for item in retriever.search(
            "amber evidence", 5, generation_id="generation-one"
        )
    ] == [generation_one.text]
    assert [
        item.chunk.text
        for item in retriever.search(
            "violet evidence", 5, generation_id="generation-two"
        )
    ] == [generation_two.text]
    assert retriever.get_chunk("chunk_shared") == legacy
    assert (
        retriever.get_chunk("chunk_shared", generation_id="generation-one").text
        == generation_one.text
    )

    reopened = BM25SparseRetriever(path)
    assert len(reopened.list_chunks()) == 3
    assert (
        reopened.get_chunk("chunk_shared", generation_id="generation-one").text
        == generation_one.text
    )

    reopened.delete_document("doc_one", generation_id="generation-one")

    assert reopened.get_chunk("chunk_shared") == legacy
    assert reopened.get_chunk("chunk_shared", generation_id="generation-one") is None
    assert (
        reopened.get_chunk("chunk_shared", generation_id="generation-two").text
        == generation_two.text
    )


def test_rebuild_replaces_only_requested_generation_and_neighbors_stay_scoped(
    tmp_path: Path,
) -> None:
    retriever = BM25SparseRetriever(tmp_path / "bm25.json")
    old_anchor = _chunk(
        "chunk_anchor", "first generation anchor", generation_id="generation-one"
    )
    old_next = _chunk(
        "chunk_next",
        "first generation neighbor",
        generation_id="generation-one",
        chunk_index=1,
    )
    other_anchor = _chunk(
        "chunk_anchor", "second generation anchor", generation_id="generation-two"
    )
    other_next = _chunk(
        "chunk_next",
        "second generation neighbor",
        generation_id="generation-two",
        chunk_index=1,
    )
    retriever.index_chunks([old_anchor, old_next], generation_id="generation-one")
    retriever.index_chunks([other_anchor, other_next], generation_id="generation-two")

    replacement = _chunk(
        "chunk_anchor", "rebuilt first generation", generation_id="generation-one"
    )
    retriever.rebuild([replacement], generation_id="generation-one")

    assert retriever.get_chunk("chunk_anchor", generation_id="generation-one").text == (
        replacement.text
    )
    assert retriever.get_chunk("chunk_next", generation_id="generation-one") is None
    assert retriever.get_chunk("chunk_next", generation_id="generation-two").text == (
        other_next.text
    )
    neighbors = retriever.section_neighbors(other_anchor, radius=1)
    assert [chunk.text for chunk in neighbors] == [other_anchor.text, other_next.text]
