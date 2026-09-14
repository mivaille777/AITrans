from __future__ import annotations

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier


def _evidence(evidence_id: str, excerpt: str) -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id=evidence_id,
        source_type="knowledge",
        source_id="doc-1",
        title="Control Paper",
        location="Section 3.4",
        excerpt=excerpt,
        score=0.9,
    )


def _citation(label: str, evidence_id: str) -> AgentCitationRef:
    return AgentCitationRef(
        citation_id=f"citation-{label.strip('[]')}",
        evidence_ids=[evidence_id],
        label=label,
    )


def test_supported_claim_with_allowed_citation_passes() -> None:
    evidence = [_evidence("e1", "The GP constrains the broad search region.")]
    citations = [_citation("[1]", "e1")]

    result = AgentClaimEvidenceVerifier().verify(
        output_text="The GP constrains the broad search region [1].",
        evidence=evidence,
        citations=citations,
    )

    assert result.passed is True
    assert result.claim_count == 1
    assert result.cited_claim_count == 1
    assert result.supported_claim_count == 1
    assert result.citation_coverage == 1.0
    assert result.support_rate == 1.0


def test_factual_claim_without_citation_fails() -> None:
    evidence = [_evidence("e1", "The GP constrains the broad search region.")]

    result = AgentClaimEvidenceVerifier().verify(
        output_text="The GP constrains the broad search region during optimization.",
        evidence=evidence,
        citations=[_citation("[1]", "e1")],
    )

    assert result.passed is False
    assert "missing_claim_citation" in result.reason_codes
    assert "citation_coverage_below_policy" in result.reason_codes


def test_unknown_citation_is_rejected() -> None:
    evidence = [_evidence("e1", "The GP constrains the broad search region.")]

    result = AgentClaimEvidenceVerifier().verify(
        output_text="The GP constrains the broad search region [9].",
        evidence=evidence,
        citations=[_citation("[1]", "e1")],
    )

    assert result.passed is False
    assert result.invalid_citation_count == 1
    assert "unknown_citation" in result.reason_codes


def test_citation_to_unrelated_evidence_fails_support_check() -> None:
    evidence = [_evidence("e1", "The actuator voltage is bounded by the safety gate.")]

    result = AgentClaimEvidenceVerifier().verify(
        output_text="The GP constrains the broad statistical search region [1].",
        evidence=evidence,
        citations=[_citation("[1]", "e1")],
    )

    assert result.passed is False
    assert result.supported_claim_count == 0
    assert "weak_claim_evidence_overlap" in result.reason_codes


def test_short_non_factual_placeholder_does_not_trigger_false_failure() -> None:
    result = AgentClaimEvidenceVerifier().verify(
        output_text="Grounded answer [1]",
        evidence=[_evidence("e1", "The GP constrains the broad search region.")],
        citations=[_citation("[1]", "e1")],
    )

    assert result.passed is True
    assert result.claim_count == 0
    assert result.reason_codes == ("no_verifiable_claims",)


def test_paragraph_end_citation_produces_supported_paragraph_signal() -> None:
    evidence = [
        _evidence(
            "e1",
            "The GP constrains the broad search region and repeated evidence-based correction reduces sensitivity to the initial controller anchor.",
        )
    ]
    output = (
        "The statistical search first limits the broad parameter region. "
        "Repeated evidence-based correction then reduces sensitivity to the initial controller anchor [1]."
    )

    result = AgentClaimEvidenceVerifier().verify(
        output_text=output,
        evidence=evidence,
        citations=[_citation("[1]", "e1")],
    )

    # Sentence-strict verification remains intentionally conservative.
    assert result.passed is False
    assert result.citation_coverage == 0.5
    # Paragraph-level signals recognize the common academic convention where
    # the citation at the paragraph end supports the paragraph as a unit.
    assert result.paragraph_count == 1
    assert result.cited_paragraph_count == 1
    assert result.supported_paragraph_count == 1
    assert result.paragraph_citation_coverage == 1.0
    assert result.paragraph_support_rate == 1.0


def test_unrelated_paragraph_citation_is_not_marked_supported() -> None:
    evidence = [_evidence("e1", "The actuator voltage is bounded by the safety gate.")]

    result = AgentClaimEvidenceVerifier().verify(
        output_text=(
            "The GP guarantees global optimality under every operating condition. "
            "It therefore eliminates all controller uncertainty [1]."
        ),
        evidence=evidence,
        citations=[_citation("[1]", "e1")],
    )

    assert result.passed is False
    assert result.paragraph_count == 1
    assert result.cited_paragraph_count == 1
    assert result.supported_paragraph_count == 0
    assert result.paragraph_support_rate == 0.0
