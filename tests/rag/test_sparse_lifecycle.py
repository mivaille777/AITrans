from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from backend.rag.models import DocumentChunk
from backend.rag.source_span import SourceSpan, resolve_source_span
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
    assert reopened.search("amber", 5, generation_id="generation-one") == []
    assert (
        BM25SparseRetriever(path).search("amber", 5, generation_id="generation-one")
        == []
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
    assert retriever.search("neighbor", 5, generation_id="generation-one") == []


def test_source_span_survives_bm25_json_restart(tmp_path: Path) -> None:
    path = tmp_path / "bm25.json"
    source_text = "Introductory text. Exact source evidence. Final notes."
    selected_text = "Exact source evidence."
    start_char = source_text.index(selected_text)
    end_char = start_char + len(selected_text)
    document_hash = sha256(b"original PDF bytes").hexdigest()
    source_uri = "file:///paper.pdf"
    span = SourceSpan.from_text(
        source_text,
        start_char=start_char,
        end_char=end_char,
        document_hash=document_hash,
        source_uri=source_uri,
        page_start=2,
        page_end=2,
    )
    chunk = DocumentChunk(
        chunk_id="chunk_source_span",
        document_id="doc_one",
        text=selected_text,
        page_number=2,
        chunk_index=0,
        start_char=start_char,
        end_char=end_char,
        source_uri=source_uri,
        document_hash=document_hash,
        source_span=span,
    )
    retriever = BM25SparseRetriever(path)
    retriever.index_chunks([chunk])

    reopened = BM25SparseRetriever(path)
    restored = reopened.get_chunk(chunk.chunk_id)

    assert restored is not None
    assert restored.source_span == span
    assert resolve_source_span(restored.source_span, source_text) == selected_text


@pytest.mark.parametrize("stored_version", [None, "scientific-v1"])
def test_tokenizer_version_change_rebuilds_from_persisted_chunks(
    tmp_path: Path,
    stored_version: str | None,
) -> None:
    path = tmp_path / "bm25.json"
    retriever = BM25SparseRetriever(path)
    retriever.index_chunks([_chunk("formula", "The measured compound was H2SO4.")])

    data = json.loads(path.read_text(encoding="utf-8"))
    if stored_version is None:
        del data["tokenizer_version"]
    else:
        data["tokenizer_version"] = stored_version
    path.write_text(json.dumps(data), encoding="utf-8")

    reopened = BM25SparseRetriever(path)

    assert reopened.search("H2SO4", 1)[0].chunk.chunk_id == "formula"
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["tokenizer_version"] == "scientific-v2"


def test_restart_search_excludes_inactive_and_unlisted_document_generations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bm25.json"
    retriever = BM25SparseRetriever(path)
    old = _chunk("old", "shared evidence", generation_id="old")
    active = _chunk("active", "shared evidence", generation_id="active")
    unauthorized = _chunk(
        "other", "shared evidence", generation_id="active"
    ).model_copy(update={"document_id": "doc_other"})
    retriever.index_chunks([old, active, unauthorized])
    reopened = BM25SparseRetriever(path)
    results = reopened.search(
        "shared evidence", 10, active_generations={"doc_one": "active"}
    )
    assert [result.chunk.chunk_id for result in results] == ["active"]
    assert reopened.search("shared evidence", 10, active_generations={}) == []
    reopened.delete_document("doc_one")
    assert (
        BM25SparseRetriever(path).search(
            "shared evidence", 10, active_generations={"doc_one": "active"}
        )
        == []
    )
