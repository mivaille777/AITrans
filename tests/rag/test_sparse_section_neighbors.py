from __future__ import annotations

from pathlib import Path

from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever


def chunk(
    chunk_id: str,
    index: int,
    *,
    path: list[str],
    document_id: str = "paper",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"content {chunk_id}",
        section_heading=path[-1],
        section_path=path,
        chunk_index=index,
    )


def test_section_neighbors_are_bounded_to_exact_document_and_leaf_section(
    tmp_path: Path,
) -> None:
    retriever = BM25SparseRetriever(tmp_path / "bm25.json")
    first = chunk("first", 0, path=["3 Methodology", "3.2 GP"])
    anchor = chunk("anchor", 1, path=["3 Methodology", "3.2 GP"])
    third = chunk("third", 2, path=["3 Methodology", "3.2 GP"])
    other_section = chunk("other-section", 3, path=["3 Methodology", "3.3 LLM"])
    other_document = chunk(
        "other-document",
        1,
        path=["3 Methodology", "3.2 GP"],
        document_id="other-paper",
    )
    retriever.index_chunks(
        [first, anchor, third, other_section, other_document]
    )

    neighbors = retriever.section_neighbors(anchor, radius=1)

    assert [item.chunk_id for item in neighbors] == ["first", "anchor", "third"]


def test_section_neighbors_without_hierarchy_degrade_to_anchor_only(tmp_path: Path) -> None:
    retriever = BM25SparseRetriever(tmp_path / "bm25.json")
    anchor = DocumentChunk(
        chunk_id="legacy",
        document_id="paper",
        text="legacy chunk",
        chunk_index=0,
    )
    retriever.index_chunks([anchor])

    assert [item.chunk_id for item in retriever.section_neighbors(anchor, 1)] == [
        "legacy"
    ]
