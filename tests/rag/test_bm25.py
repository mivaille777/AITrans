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


def test_ranked_scan_continues_past_out_of_scope_and_inactive_hits(tmp_path):
    retriever = make_retriever(tmp_path)
    retriever.index_chunks([chunk("outside", "water", document_id="outside")])
    retriever.index_chunks([chunk("stale", "water", document_id="allowed")], generation_id="old")
    retriever.index_chunks([chunk("reference", "water", document_id="allowed", section="References")], generation_id="current")
    retriever.index_chunks([
        chunk("a", "water and a long discussion", document_id="allowed"),
        chunk("b", "water and a long discussion", document_id="allowed"),
    ], generation_id="current")
    hits = retriever.search("water", 2, VectorSearchFilter(document_ids=["allowed"]),
                            active_generations={"allowed": "current"})
    assert [hit.chunk.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].sparse_score == hits[1].sparse_score
    assert retriever.search("water", 2, active_generations={}) == []


def test_selective_scope_finds_low_ranked_hits_without_dropping_ties(tmp_path):
    retriever = make_retriever(tmp_path)
    retriever.index_chunks([
        *[chunk(f"outside-{i}", "water", document_id="outside") for i in range(200)],
        chunk("a", "water with additional context", document_id="allowed").model_copy(update={"metadata": {"selected": True}}),
        chunk("b", "water with additional context", document_id="allowed").model_copy(update={"metadata": {"selected": True}}),
    ])
    hits = retriever.search("water", 2, VectorSearchFilter(metadata={"selected": True}))
    assert [hit.chunk.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].sparse_score == hits[1].sparse_score


def test_reference_classification_updates_on_replacement_and_restart(tmp_path):
    retriever = make_retriever(tmp_path)
    references = chunk("shared", "water tank controller", section="References")
    retriever.index_chunks([references])
    filters = VectorSearchFilter(exclude_references=True)
    assert retriever.search("water tank", 3, filters) == []
    retriever.index_chunks([chunk("shared", "water tank controller", section="Methods")])
    assert [item.chunk.chunk_id for item in retriever.search("water tank", 3, filters)] == ["shared"]
    restarted = make_retriever(tmp_path)
    assert [item.chunk.chunk_id for item in restarted.search("water tank", 3, filters)] == ["shared"]
    restarted.delete_document("doc_one")
    assert restarted.search("water tank", 3, filters) == []


def test_bm25_vectorized_scores_keep_numeric_formula_and_current_parameters():
    import math

    from backend.rag.sparse.bm25 import BM25Index

    index = BM25Index()
    index.rebuild({"a": ["water", "water", "tank"], "b": ["water"], "c": []})
    for k1, b in ((1.5, .75), (.8, 0.0), (2.0, 1.0)):
        index.k1, index.b = k1, b
        scores = index.score(["water", "water", "absent"])
        idf = math.log(1 + (3 - 2 + .5) / (2 + .5))
        expected = {key: idf * (tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (4 / 3))))
                    for key, tf, length in (("a", 2, 3), ("b", 1, 1))}
        assert scores == pytest.approx(expected, abs=1e-12)
    index.rebuild({})
    assert index.score(["water"]) == {}


def test_in_progress_sparse_rebuild_does_not_mutate_published_scoring_arrays(tmp_path, monkeypatch):
    from threading import Event, Thread

    from backend.rag.sparse.bm25 import BM25Index

    retriever = make_retriever(tmp_path)
    retriever.index_chunks([chunk("old", "water tank")])
    ready, release = Event(), Event()
    rebuild = BM25Index.rebuild

    def blocked_rebuild(index, documents):
        rebuild(index, documents)
        ready.set()
        assert release.wait(5)

    monkeypatch.setattr(BM25Index, "rebuild", blocked_rebuild)
    worker = Thread(target=lambda: retriever.index_chunks([chunk("new", "water tank")]))
    worker.start()
    try:
        assert ready.wait(5)
        assert [item.chunk.chunk_id for item in retriever.search("water", 3)] == ["old"]
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert {item.chunk.chunk_id for item in retriever.search("water", 3)} == {"old", "new"}


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
