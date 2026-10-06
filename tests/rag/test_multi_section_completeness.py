from types import SimpleNamespace

import pytest

from backend.rag.config import RagRetrievalConfig
from backend.rag.models import DocumentChunk, RetrievalCandidate
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import (
    detect_structural_intent,
    order_structural_candidates,
    section_match_priority,
)


@pytest.mark.parametrize(
    "query",
    [
        "分别总结研究方法、实验结果、局限性和结论。",
        "Summarize the methods, results, limitations and conclusions.",
    ],
)
def test_all_requested_sections_are_preserved(query):
    intent = detect_structural_intent(query)
    assert intent.name == "multi_section"
    assert {"methods", "results", "limitations", "conclusions"}.issubset(
        intent.section_aliases
    )


def chunk(identifier, section, index, document="doc"):
    return DocumentChunk(
        chunk_id=identifier,
        document_id=document,
        chunk_index=index,
        text=f"{section}: substantive source fact {index}.",
        section_heading=section,
    )


def test_long_methods_section_does_not_starve_later_sections(tmp_path):
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    chunks = [chunk(f"method-{i}", "Methods", i) for i in range(30)]
    chunks += [
        chunk("result", "Results", 31),
        chunk("limit", "Limitations", 32),
        chunk("conclusion", "Conclusions", 33),
    ]
    chunks += [chunk("private-result", "Results", 0, document="private")]
    sparse.index_chunks(chunks, generation_id="active")
    sparse.index_chunks(
        [chunk("retired-result", "Results", 0)], generation_id="retired"
    )
    intent = detect_structural_intent(
        "Summarize methods, results, limitations and conclusions"
    )
    results = sparse.search_sections(
        intent.section_aliases,
        4,
        VectorSearchFilter(document_ids=["doc"]),
        active_generations={"doc": "active"},
    )
    assert [r.chunk.chunk_id for r in results] == [
        "method-0",
        "result",
        "conclusion",
        "limit",
    ]
    ordered, _ = order_structural_candidates(results, intent.section_aliases)
    assert {r.chunk.section_heading for r in ordered} == {
        "Methods",
        "Results",
        "Limitations",
        "Conclusions",
    }


def test_structural_coverage_survives_fusion_pool_cutoff():
    body = [
        RetrievalCandidate(
            chunk=chunk(f"body-{i}", "Introduction", i),
            rank=i + 1,
            dense_score=1.0,
            sparse_score=1.0,
        )
        for i in range(20)
    ]
    structural = [
        RetrievalCandidate(
            chunk=chunk(label, label, i + 20), rank=i + 1, sparse_score=3.0
        )
        for i, label in enumerate(["Methods", "Results", "Limitations", "Conclusions"])
    ]
    service = RetrievalService(
        embedding_provider=SimpleNamespace(embed_query=lambda query: [1.0, 0.0]),
        vector_store=SimpleNamespace(search=lambda vector, **kwargs: body),
        sparse_retriever=SimpleNamespace(
            search=lambda *args, **kwargs: body,
            search_sections=lambda *args, **kwargs: structural,
        ),
        config=RagRetrievalConfig(small_to_big_enabled=False),
    )
    intent = detect_structural_intent(
        "Summarize methods, results, limitations and conclusions"
    )
    result = service.retrieve(
        "overview", section_hints=intent.section_aliases, final_top_k=4
    )
    assert {r.chunk.section_heading for r in result.candidates} == {
        "Methods",
        "Results",
        "Limitations",
        "Conclusions",
    }
    assert result.metadata["fusion_count"] == 20


def test_flat_numbered_pdf_sections_inherit_scoped_ancestor_and_prefer_body(tmp_path):
    sparse = BM25SparseRetriever(tmp_path / "bm25.json")
    header = chunk("header", "4. Results", 0)
    header.text = "4. Results"
    body = chunk("body", "4.2. Overall Performance", 1)
    method = chunk("method", "3. Methods", 2)
    sparse.index_chunks([header, body, method], generation_id="active")
    # Same numbering in another document/generation must not become an ancestor.
    sparse.index_chunks(
        [chunk("private", "4. Limitations", 0, document="private")],
        generation_id="active",
    )
    sparse.index_chunks(
        [chunk("retired", "4. Limitations", 0)], generation_id="retired"
    )
    intent = detect_structural_intent("Summarize methods and results")
    results = sparse.search_sections(
        intent.section_aliases,
        2,
        VectorSearchFilter(document_ids=["doc"]),
        active_generations={"doc": "active"},
    )
    assert {r.chunk.chunk_id for r in results} == {"method", "body"}
    retrieved_body = next(r for r in results if r.chunk.chunk_id == "body")
    assert retrieved_body.metadata["structural_parent_headings"] == ["4. Results"]
    assert retrieved_body.chunk.section_path == body.section_path


def test_subsection_coverage_survives_strong_scores_in_one_leaf():
    candidates = [
        RetrievalCandidate(
            chunk=chunk(f"detail-{i}", "3.1. Method Overview", i), rerank_score=0.99
        )
        for i in range(20)
    ]
    candidates += [
        RetrievalCandidate(
            chunk=chunk("other-method", "3.2. Method Interface", 21), rerank_score=0.1
        ),
        RetrievalCandidate(
            chunk=chunk("protocol", "4.1. Experimental Protocol", 22), rerank_score=0.9
        ),
        RetrievalCandidate(
            chunk=chunk("performance", "4.2. Overall Performance", 23), rerank_score=0.1
        ),
        RetrievalCandidate(
            chunk=chunk("root-results", "4. Experimental Design and Results", 24),
            rerank_score=0.9,
        ),
    ]
    candidates[-1].chunk.text = candidates[-1].chunk.section_heading
    intent = detect_structural_intent("Summarize methods and results")
    ordered, _ = order_structural_candidates(candidates, intent.section_aliases)
    assert {c.chunk.chunk_id for c in ordered[:4]} == {
        "detail-0",
        "other-method",
        "protocol",
        "performance",
    }


def test_body_mentions_do_not_override_known_section_provenance():
    candidate = RetrievalCandidate(
        chunk=chunk("authors", "CRediT authorship contribution statement", 0)
    )
    candidate.chunk.text = (
        "The authors developed the proposed method and reviewed results."
    )
    assert section_match_priority(candidate, ("methods", "method", "results")) == 0
    candidate.chunk.section_heading = ""
    candidate.chunk.text = "Methods\nThe procedure uses a local controller."
    assert section_match_priority(candidate, ("methods",)) == 1
