from __future__ import annotations

from pathlib import Path

import pytest

from backend.rag.models import DocumentChunk
from backend.rag.sparse import BM25SparseRetriever, SparseRetriever
from backend.rag.stores.base import VectorSearchFilter


def chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "doc_one",
    title: str = "",
    section: str = "",
    page: int | None = None,
    chunk_index: int = 0,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        section_heading=section,
        page_number=page,
        chunk_index=chunk_index,
    )


def make_retriever(tmp_path: Path) -> BM25SparseRetriever:
    return BM25SparseRetriever(tmp_path / "bm25_index.json")


@pytest.mark.parametrize("query", ["M10", "J_seg", "GP-UCB"])
def test_exact_identifier_match_ranks_first(tmp_path: Path, query: str) -> None:
    retriever = make_retriever(tmp_path)
    exact = chunk(
        "chunk_exact", f"The controller reports {query} as the selected variable."
    )
    common = chunk(
        "chunk_common", "The controller reports a common variable and result."
    )
    retriever.index_chunks([common, exact])

    results = retriever.search(query, top_k=2)

    assert results[0].chunk.chunk_id == "chunk_exact"
    assert results[0].sparse_score > 0


def test_title_and_section_heading_participate_in_sparse_search(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk(
                "references",
                "[1] A. Author, Control Systems.",
                title="Water Tank Paper",
                section="References",
            ),
            chunk("body", "ordinary experimental discussion"),
        ]
    )

    assert retriever.search("References", 1)[0].chunk.chunk_id == "references"
    assert retriever.search("Water Tank Paper", 1)[0].chunk.chunk_id == "references"


def test_section_lookup_matches_numbered_heading_and_preserves_page_order(
    tmp_path: Path,
) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk(
                "body",
                "results body",
                section="4 Results",
                page=7,
                chunk_index=1,
            ),
            chunk(
                "ref-2",
                "[3] third reference",
                section="6. References",
                page=11,
                chunk_index=3,
            ),
            chunk(
                "ref-1",
                "[1] first reference",
                section="References",
                page=10,
                chunk_index=2,
            ),
        ]
    )

    results = retriever.search_sections(("references", "bibliography"), 10)

    assert [item.chunk.chunk_id for item in results] == ["ref-1", "ref-2"]
    assert all(item.metadata["structural_section_match"] is True for item in results)


def test_section_lookup_respects_document_filter(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk(
                "ref-a",
                "[1] A",
                document_id="doc-a",
                section="References",
            ),
            chunk(
                "ref-b",
                "[1] B",
                document_id="doc-b",
                section="References",
            ),
        ]
    )

    results = retriever.search_sections(
        ("references",),
        10,
        VectorSearchFilter(document_ids=["doc-b"]),
    )

    assert [item.chunk.chunk_id for item in results] == ["ref-b"]


def test_chinese_term_retrieval(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk("chunk_control", "高斯过程用于PID参数优化"),
            chunk("chunk_vision", "卷积网络用于图像识别"),
        ]
    )

    results = retriever.search("高斯优化", top_k=2)

    assert results[0].chunk.chunk_id == "chunk_control"


def test_mixed_language_query(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk("chunk_match", "使用 GP-UCB 优化控制器参数"),
            chunk("chunk_other", "A general optimization introduction"),
        ]
    )

    assert retriever.search("GP-UCB 控制", top_k=1)[0].chunk.chunk_id == "chunk_match"


def test_rare_identifier_outweighs_common_words(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk("chunk_rare", "method method method J_seg"),
            chunk("chunk_common", "method method method method method"),
        ]
    )

    results = retriever.search("method J_seg", top_k=2)

    assert results[0].chunk.chunk_id == "chunk_rare"


def test_delete_document(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks(
        [
            chunk("chunk_one", "M10 controller", document_id="doc_one"),
            chunk("chunk_two", "M10 experiment", document_id="doc_two"),
        ]
    )

    retriever.delete_document("doc_one")

    assert [item.chunk.chunk_id for item in retriever.search("M10", 10)] == [
        "chunk_two"
    ]


def test_persistence_restart(tmp_path: Path) -> None:
    path = tmp_path / "bm25_index.json"
    first = BM25SparseRetriever(path)
    first.index_chunks([chunk("chunk_saved", "Eq.17 defines the objective")])

    second = BM25SparseRetriever(path)

    assert second.search("Eq.17", 1)[0].chunk.chunk_id == "chunk_saved"


def test_empty_query_and_top_k_boundary(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.index_chunks([chunk("chunk_one", "content")])

    assert retriever.search("...", 1) == []
    with pytest.raises(ValueError, match="top_k"):
        retriever.search("content", 0)
    with pytest.raises(ValueError, match="top_k"):
        retriever.search_sections(("references",), 0)


def test_duplicate_index_is_idempotent_and_protocol_is_satisfied(
    tmp_path: Path,
) -> None:
    retriever = make_retriever(tmp_path)
    item = chunk("chunk_one", "PID tuning")

    retriever.index_chunks([item])
    retriever.index_chunks([item])

    assert isinstance(retriever, SparseRetriever)
    assert len(retriever.search("PID", 10)) == 1


def test_tie_order_is_deterministic(tmp_path: Path) -> None:
    retriever = make_retriever(tmp_path)
    retriever.rebuild([chunk("chunk_b", "same term"), chunk("chunk_a", "same term")])

    assert [item.chunk.chunk_id for item in retriever.search("same", 2)] == [
        "chunk_a",
        "chunk_b",
    ]
