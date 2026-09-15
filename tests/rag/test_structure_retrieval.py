from __future__ import annotations

from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.structure_retrieval import (
    build_structural_queries,
    detect_structural_intent,
    normalize_section_heading,
    promote_structural_candidates,
)


def _candidate(
    chunk_id: str,
    *,
    section: str,
    page: int,
    chunk_index: int,
    document_id: str = "wen-paper",
    chunk_type: str = "paragraph_group",
    labels: list[str] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            title="An experiment of using a large language model to control a water tank system",
            text=f"{section}\nEvidence {chunk_id}",
            section_heading=section,
            page_number=page,
            chunk_index=chunk_index,
            chunk_type=chunk_type,
            metadata={"special_labels": labels or []},
        ),
        rank=chunk_index + 1,
    )


def test_detects_bibliography_intent_across_chinese_and_english() -> None:
    chinese = detect_structural_intent("Wen这篇文章用到的参考文献有哪些")
    english = detect_structural_intent("List the bibliography used by this paper")

    assert chinese is not None
    assert english is not None
    assert chinese.name == "bibliography"
    assert english.name == "bibliography"
    assert "references" in chinese.section_aliases
    assert chinese.final_top_k > 8


def test_detects_common_academic_sections_and_special_artifacts() -> None:
    assert detect_structural_intent("这篇论文的最终结论是什么").name == "conclusion"
    assert detect_structural_intent("What are the study limitations?").name == "limitations"
    assert detect_structural_intent("未来工作是什么").name == "future_work"
    assert detect_structural_intent("What does Table 3 show?").name == "table"
    assert detect_structural_intent("解释一下 Fig. 4").name == "figure"
    assert detect_structural_intent("Equation 7 defines what?").name == "equation"
    assert detect_structural_intent("公式 5 的含义是什么").name == "equation"


def test_structural_queries_add_heading_vocabulary_without_only_increasing_top_k() -> None:
    intent = detect_structural_intent("这篇文章有哪些参考文献")
    queries = build_structural_queries(
        ("Wen water tank paper cited literature",),
        original_query="这篇文章有哪些参考文献",
        intent=intent,
    )

    assert len(queries) == 3
    assert "References" in queries[0]
    assert queries[1].startswith("References")
    assert queries[2] == "Wen water tank paper cited literature"


def test_structural_promotion_keeps_reference_chunks_first_and_in_document_order() -> None:
    result = RetrievalResult(
        query="references",
        candidates=[
            _candidate("body", section="Experiments", page=7, chunk_index=0),
            _candidate(
                "ref-2",
                section="6 References",
                page=11,
                chunk_index=4,
                chunk_type="reference_group",
            ),
            _candidate(
                "ref-1",
                section="References",
                page=10,
                chunk_index=3,
                chunk_type="reference_group",
            ),
        ],
    )
    intent = detect_structural_intent("参考文献有哪些")

    promoted = promote_structural_candidates(result, intent=intent, limit=3)

    assert [item.chunk.chunk_id for item in promoted.candidates] == [
        "ref-1",
        "ref-2",
        "body",
    ]
    assert promoted.metadata["structural_intent"] == "bibliography"
    assert promoted.metadata["structural_match_count"] == 2


def test_table_and_figure_chunks_match_by_type_even_inside_results_section() -> None:
    table_result = RetrievalResult(
        query="Table 3",
        candidates=[
            _candidate("body", section="4 Results", page=7, chunk_index=0),
            _candidate(
                "table-3",
                section="4 Results",
                page=8,
                chunk_index=1,
                chunk_type="table",
                labels=["Table 3"],
            ),
        ],
    )
    figure_result = RetrievalResult(
        query="Figure 4",
        candidates=[
            _candidate("body", section="4 Results", page=7, chunk_index=0),
            _candidate(
                "figure-4",
                section="4 Results",
                page=9,
                chunk_index=2,
                chunk_type="figure_context",
                labels=["Fig. 4"],
            ),
        ],
    )

    table = promote_structural_candidates(
        table_result,
        intent=detect_structural_intent("What does Table 3 show?"),
        limit=2,
    )
    figure = promote_structural_candidates(
        figure_result,
        intent=detect_structural_intent("解释一下 Fig. 4"),
        limit=2,
    )

    assert table.candidates[0].chunk.chunk_id == "table-3"
    assert figure.candidates[0].chunk.chunk_id == "figure-4"


def test_equation_chunk_matches_by_type_outside_equation_named_section() -> None:
    result = RetrievalResult(
        query="Equation 7",
        candidates=[
            _candidate("body", section="3 Methodology", page=5, chunk_index=0),
            _candidate(
                "eq-7",
                section="3 Methodology",
                page=6,
                chunk_index=1,
                chunk_type="equation_context",
                labels=["Eq. 7"],
            ),
        ],
    )

    promoted = promote_structural_candidates(
        result,
        intent=detect_structural_intent("What does Equation 7 mean?"),
        limit=2,
    )

    assert promoted.candidates[0].chunk.chunk_id == "eq-7"


def test_structural_promotion_preserves_cross_document_relevance_order() -> None:
    result = RetrievalResult(
        query="references",
        candidates=[
            _candidate(
                "more-relevant",
                section="References",
                page=12,
                chunk_index=9,
                document_id="z-document",
                chunk_type="reference_group",
            ),
            _candidate(
                "less-relevant",
                section="References",
                page=2,
                chunk_index=1,
                document_id="a-document",
                chunk_type="reference_group",
            ),
        ],
    )
    intent = detect_structural_intent("参考文献有哪些")

    promoted = promote_structural_candidates(result, intent=intent, limit=2)

    assert [item.chunk.chunk_id for item in promoted.candidates] == [
        "more-relevant",
        "less-relevant",
    ]


def test_section_heading_normalization_removes_number_prefixes() -> None:
    assert normalize_section_heading("6. References") == "references"
    assert normalize_section_heading("VI - CONCLUSIONS") == "conclusions"
