from __future__ import annotations

import pytest

from backend.models.agent_react import AgentRetrievalObservation
from backend.models.agent_runtime import AgentEvidenceItem
from backend.services.agent_evidence_gate_service import (
    AgentEvidenceGatePolicy,
    AgentEvidenceGateService,
)


def _evidence(
    name: str,
    *,
    source: str = "doc-1",
    location: str | None = None,
    score: float | None = 0.9,
) -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id=f"evidence:{name}",
        source_type="knowledge",
        source_id=source,
        title="Paper",
        resource_url="file:///paper.pdf",
        location=location or f"Section {name}",
        excerpt=f"Evidence {name}",
        score=score,
    )


def _retrieval(
    *,
    evidence_count: int,
    novel: int,
    fallback_reason: str = "",
) -> AgentRetrievalObservation:
    return AgentRetrievalObservation(
        query="bounded retrieval query",
        retrieval_strategy="hybrid",
        result_count=evidence_count,
        evidence_count=evidence_count,
        citation_count=evidence_count,
        novel_evidence_count=novel,
        fallback_reason=fallback_reason,
    )


def test_gate_retrieves_when_no_evidence_exists() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(),
        latest_retrieval=_retrieval(evidence_count=0, novel=0),
        search_count=1,
        remaining_searches=2,
    )

    assert gate.action == "retrieve"
    assert gate.evidence_count == 0
    assert "no_evidence" in gate.reason_codes


def test_gate_refines_when_evidence_exists_but_coverage_is_weak() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(_evidence("one"),),
        latest_retrieval=_retrieval(evidence_count=1, novel=1),
        search_count=1,
        remaining_searches=2,
    )

    assert gate.action == "refine"
    assert gate.coverage_score < 1.0
    assert "insufficient_evidence_count" in gate.reason_codes
    assert "novel_evidence_found" in gate.reason_codes


def test_gate_stops_when_cumulative_evidence_is_sufficient_and_diverse() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(
            _evidence("one", location="Section 2"),
            _evidence("two", location="Section 5"),
        ),
        latest_retrieval=_retrieval(evidence_count=1, novel=1),
        search_count=2,
        remaining_searches=1,
    )

    assert gate.action == "stop"
    assert gate.evidence_count == 2
    assert gate.unique_location_count == 2
    assert "evidence_sufficient" in gate.reason_codes


def test_gate_stops_after_refinement_adds_no_novel_evidence() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(_evidence("one"),),
        latest_retrieval=_retrieval(evidence_count=1, novel=0),
        search_count=2,
        remaining_searches=1,
    )

    assert gate.action == "stop"
    assert "no_novel_evidence_after_refinement" in gate.reason_codes


def test_gate_retrieves_again_when_weak_result_used_fallback() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(_evidence("one"),),
        latest_retrieval=_retrieval(
            evidence_count=1,
            novel=1,
            fallback_reason="reranker_unavailable",
        ),
        search_count=1,
        remaining_searches=2,
    )

    assert gate.action == "retrieve"
    assert gate.retrieval_fallback is True
    assert "retrieval_fallback" in gate.reason_codes


def test_gate_stops_when_search_budget_is_exhausted() -> None:
    gate = AgentEvidenceGateService().assess(
        evidence=(_evidence("one"),),
        latest_retrieval=_retrieval(evidence_count=1, novel=1),
        search_count=3,
        remaining_searches=0,
    )

    assert gate.action == "stop"
    assert gate.remaining_searches == 0
    assert gate.reason_codes[0] == "retrieval_budget_exhausted"


def test_gate_does_not_treat_raw_score_as_calibrated_confidence() -> None:
    service = AgentEvidenceGateService()
    high = service.assess(
        evidence=(_evidence("one", score=100.0),),
        latest_retrieval=_retrieval(evidence_count=1, novel=1),
        search_count=1,
        remaining_searches=2,
    )
    low = service.assess(
        evidence=(_evidence("one", score=-100.0),),
        latest_retrieval=_retrieval(evidence_count=1, novel=1),
        search_count=1,
        remaining_searches=2,
    )

    assert high.action == low.action == "refine"
    assert high.quality_score == low.quality_score


def test_gate_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="target_evidence_count must be positive"):
        AgentEvidenceGatePolicy(target_evidence_count=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        AgentEvidenceGatePolicy(
            target_evidence_count=2,
            minimum_stop_evidence_count=3,
        )
    with pytest.raises(ValueError, match="at least 2"):
        AgentEvidenceGatePolicy(no_novelty_stop_after_searches=1)
