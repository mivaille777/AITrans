from __future__ import annotations

from pathlib import Path

from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str,
    label: str,
    text: str,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="paper",
        title="Scientific Paper",
        text=text,
        section_heading="4 Results",
        section_path=["4 Results"],
        chunk_type=chunk_type,
        page_number=4,
        chunk_index=0,
        metadata={"special_labels": [label]},
    )


def test_structural_sparse_search_recalls_table_by_chunk_type(tmp_path: Path) -> None:
    retriever = BM25SparseRetriever(tmp_path / "bm25.json")
    table = _chunk(
        "table-3",
        chunk_type="table",
        label="Table 3",
        text="| Method | J |\n|---|---|\n| M10 | 0.40 |",
    )
    body = DocumentChunk(
        chunk_id="body",
        document_id="paper",
        text="General results discussion.",
        section_heading="4 Results",
        section_path=["4 Results"],
        chunk_index=1,
    )
    retriever.index_chunks([body, table])

    results = retriever.search_sections(("table", "tables"), 5)

    assert [item.chunk.chunk_id for item in results] == ["table-3"]
    assert results[0].metadata["structural_section_match"] is True


def test_sparse_search_indexes_special_labels_and_chunk_type(tmp_path: Path) -> None:
    retriever = BM25SparseRetriever(tmp_path / "bm25.json")
    equation = _chunk(
        "eq-7",
        chunk_type="equation_context",
        label="Eq. 7",
        text="J = IAE + 0.1 U",
    )
    retriever.index_chunks([equation])

    assert retriever.search("Eq. 7", 1)[0].chunk.chunk_id == "eq-7"
    assert retriever.search_sections(("equation", "formula"), 5)[0].chunk.chunk_id == "eq-7"
