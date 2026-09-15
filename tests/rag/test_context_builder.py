from __future__ import annotations

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.citation_service import build_evidence_citations
from backend.rag.context_builder import GroundedContextBuilder


def _evidence(
    evidence_id: str,
    *,
    rank: int,
    score: float,
    excerpt: str = "Bounded evidence.",
) -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id=evidence_id,
        source_type="knowledge",
        source_id=f"doc-{evidence_id}",
        title=f"Paper {evidence_id}",
        resource_url=f"file:///{evidence_id}.pdf",
        location=f"Page {rank} · Section {rank}.1",
        excerpt=excerpt,
        score=score,
        metadata={"rank": rank, "internal_debug": "must not enter prompt"},
    )


def test_context_formats_evidence_and_program_citations() -> None:
    evidence = [_evidence("evidence:1", rank=1, score=0.9)]
    citations = build_evidence_citations(evidence)

    context = GroundedContextBuilder().build(evidence, citations)

    assert "[C1] [1]" in context.text
    assert "Title: Paper evidence:1" in context.text
    assert "Location: Page 1 · Section 1.1" in context.text
    assert "Evidence: Bounded evidence." in context.text
    assert "citation-1 => [1] => evidence:1" in context.text
    assert "internal_debug" not in context.text
    assert context.included_evidence_ids == ("evidence:1",)


def test_context_override_is_supplemental_without_mutating_anchor_evidence() -> None:
    evidence = [_evidence("evidence:1", rank=1, score=0.9, excerpt="anchor only")]
    citations = build_evidence_citations(evidence)

    context = GroundedContextBuilder().build(
        evidence,
        citations,
        context_overrides={
            "evidence:1": "previous context\n\nfollowing context"
        },
    )

    assert "Evidence: anchor only" in context.text
    assert "Supplemental Same-Section Context" in context.text
    assert "not independently citable" in context.text
    assert "previous context" in context.text
    assert "following context" in context.text
    assert evidence[0].excerpt == "anchor only"
    assert evidence[0].evidence_id == "evidence:1"
    assert citations[0].evidence_ids == ["evidence:1"]


def test_context_budget_truncation_is_deterministic_and_ranked() -> None:
    evidence = [
        _evidence("evidence:rank-2", rank=2, score=0.99, excerpt="B" * 260),
        _evidence("evidence:rank-1", rank=1, score=0.40, excerpt="A" * 260),
        _evidence("evidence:rank-3", rank=3, score=0.70, excerpt="C" * 260),
    ]
    citations = build_evidence_citations(evidence)
    builder = GroundedContextBuilder(max_context_tokens=300)

    first = builder.build(evidence, citations)
    second = builder.build(evidence, citations)

    assert first == second
    assert first.estimated_tokens <= 300
    assert first.included_evidence_ids == ("evidence:rank-1",)
    assert first.omitted_evidence_ids == (
        "evidence:rank-2",
        "evidence:rank-3",
    )


def test_score_orders_evidence_when_retrieval_rank_is_missing() -> None:
    high = _evidence("evidence:high", rank=1, score=0.9)
    low = _evidence("evidence:low", rank=1, score=0.2)
    high.metadata.pop("rank")
    low.metadata.pop("rank")
    evidence = [low, high]

    context = GroundedContextBuilder().build(
        evidence,
        build_evidence_citations(evidence),
    )

    assert context.included_evidence_ids == ("evidence:high", "evidence:low")


def test_context_contains_all_grounding_safety_rules() -> None:
    evidence = [_evidence("evidence:1", rank=1, score=0.9)]
    context = GroundedContextBuilder().build(
        evidence,
        build_evidence_citations(evidence),
    )

    assert "State clearly when Evidence is insufficient" in context.text
    assert "Do not invent sources" in context.text
    assert "Use only the allowed display labels" in context.text
    assert "interpretation-only" in context.text
    assert "Do not make a factual claim supported only by Supplemental Context" in context.text
    assert "Internal retrieval scores are not user facts" in context.text
