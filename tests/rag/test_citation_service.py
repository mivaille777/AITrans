from __future__ import annotations

import pytest

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.citation_service import CitationService, build_evidence_citations
from backend.rag.exceptions import RagInvariantError


def _evidence(evidence_id: str) -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id=evidence_id,
        source_type="knowledge",
        source_id="doc-1",
        excerpt=f"Excerpt for {evidence_id}",
    )


def test_citations_follow_deterministic_evidence_order() -> None:
    evidence = [_evidence("evidence:b"), _evidence("evidence:a")]

    first = build_evidence_citations(evidence)
    second = build_evidence_citations(evidence)

    assert first == second
    assert [item.citation_id for item in first] == ["citation-1", "citation-2"]
    assert [item.label for item in first] == ["[1]", "[2]"]
    assert [item.evidence_ids for item in first] == [
        ["evidence:b"],
        ["evidence:a"],
    ]


def test_citation_ids_are_unique() -> None:
    citations = build_evidence_citations(
        [_evidence("evidence:1"), _evidence("evidence:2")]
    )

    assert len({item.citation_id for item in citations}) == len(citations)


def test_unknown_evidence_is_rejected_during_build_and_validation() -> None:
    evidence = [_evidence("evidence:known")]
    service = CitationService()

    with pytest.raises(RagInvariantError, match="unknown evidence_id"):
        service.build(evidence, evidence_groups=[["evidence:missing"]])
    with pytest.raises(RagInvariantError, match="unknown evidence_id"):
        service.validate(
            [
                AgentCitationRef(
                    citation_id="citation-1",
                    evidence_ids=["evidence:missing"],
                    label="[1]",
                )
            ],
            evidence,
        )


def test_duplicate_evidence_and_duplicate_groups_are_deduped() -> None:
    evidence = [
        _evidence("evidence:1"),
        _evidence("evidence:1"),
        _evidence("evidence:2"),
    ]

    default_citations = build_evidence_citations(evidence)
    grouped = build_evidence_citations(
        evidence,
        evidence_groups=[
            ["evidence:1", "evidence:1"],
            ["evidence:1"],
            ["evidence:2"],
        ],
    )

    assert [item.evidence_ids for item in default_citations] == [
        ["evidence:1"],
        ["evidence:2"],
    ]
    assert [item.evidence_ids for item in grouped] == [
        ["evidence:1"],
        ["evidence:2"],
    ]


def test_one_citation_can_reference_multiple_verified_evidence_items() -> None:
    evidence = [_evidence("evidence:1"), _evidence("evidence:2")]

    citations = build_evidence_citations(
        evidence,
        evidence_groups=[["evidence:2", "evidence:1", "evidence:2"]],
    )

    assert citations == [
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence:2", "evidence:1"],
            label="[1]",
        )
    ]


def test_empty_evidence_produces_no_citations() -> None:
    assert build_evidence_citations([]) == []
