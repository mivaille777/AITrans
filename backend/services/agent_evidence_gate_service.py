from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from backend.models.agent_react import (
    AgentEvidenceGateAssessment,
    AgentRetrievalObservation,
)
from backend.models.agent_runtime import AgentEvidenceItem


@dataclass(frozen=True, slots=True)
class AgentEvidenceGatePolicy:
    """Deterministic thresholds for bounded retrieval sufficiency decisions."""

    target_evidence_count: int = 3
    minimum_stop_evidence_count: int = 2
    target_diversity_count: int = 2
    no_novelty_stop_after_searches: int = 2

    def __post_init__(self) -> None:
        if self.target_evidence_count < 1:
            raise ValueError("target_evidence_count must be positive")
        if self.minimum_stop_evidence_count < 1:
            raise ValueError("minimum_stop_evidence_count must be positive")
        if self.minimum_stop_evidence_count > self.target_evidence_count:
            raise ValueError(
                "minimum_stop_evidence_count cannot exceed target_evidence_count"
            )
        if self.target_diversity_count < 1:
            raise ValueError("target_diversity_count must be positive")
        if self.no_novelty_stop_after_searches < 2:
            raise ValueError("no_novelty_stop_after_searches must be at least 2")


class AgentEvidenceGateService:
    """Assess whether another knowledge retrieval is justified.

    The gate is intentionally deterministic. It uses cumulative evidence count,
    provenance diversity, latest-search novelty, retrieval fallback state, and
    remaining search budget. Raw retrieval scores are never treated as a shared
    calibrated confidence scale because dense, sparse, fusion, and reranker
    scores can have different meanings and ranges.
    """

    def __init__(self, policy: AgentEvidenceGatePolicy | None = None) -> None:
        self.policy = policy or AgentEvidenceGatePolicy()

    @staticmethod
    def _unique_nonempty(values: Sequence[str]) -> int:
        return len({str(value or "").strip() for value in values if str(value or "").strip()})

    @staticmethod
    def _bounded_ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return max(0.0, min(1.0, float(numerator) / float(denominator)))

    @staticmethod
    def _optional_score_presence(evidence: Sequence[AgentEvidenceItem]) -> float:
        """Return only score availability, not a cross-retriever confidence value."""

        if not evidence:
            return 0.0
        available = sum(
            item.score is not None and isfinite(float(item.score))
            for item in evidence
        )
        return max(0.0, min(1.0, available / len(evidence)))

    def assess(
        self,
        *,
        evidence: Sequence[AgentEvidenceItem],
        latest_retrieval: AgentRetrievalObservation,
        search_count: int,
        remaining_searches: int,
    ) -> AgentEvidenceGateAssessment:
        frozen = tuple(evidence)
        evidence_count = len({item.evidence_id for item in frozen if item.evidence_id})
        unique_source_count = self._unique_nonempty([item.source_id for item in frozen])
        unique_location_count = self._unique_nonempty([item.location for item in frozen])
        latest_novel = max(0, int(latest_retrieval.novel_evidence_count))
        searches = max(0, int(search_count))
        remaining = max(0, int(remaining_searches))
        retrieval_fallback = bool(latest_retrieval.fallback_reason.strip())

        coverage_score = self._bounded_ratio(
            evidence_count,
            self.policy.target_evidence_count,
        )
        diversity_signal = max(unique_source_count, unique_location_count)
        diversity_score = self._bounded_ratio(
            diversity_signal,
            self.policy.target_diversity_count,
        )
        novelty_score = self._bounded_ratio(
            latest_novel,
            max(1, latest_retrieval.evidence_count),
        )
        score_presence = self._optional_score_presence(frozen)
        quality_score = (
            0.50 * coverage_score
            + 0.25 * diversity_score
            + 0.20 * novelty_score
            + 0.05 * score_presence
        )
        if retrieval_fallback:
            quality_score -= 0.10
        quality_score = round(max(0.0, min(1.0, quality_score)), 4)

        reasons: list[str] = []
        action = "refine"

        if remaining <= 0:
            action = "stop"
            reasons.append("retrieval_budget_exhausted")
        elif evidence_count == 0:
            action = "retrieve"
            reasons.append("no_evidence")
            if retrieval_fallback:
                reasons.append("retrieval_fallback")
        elif (
            searches >= self.policy.no_novelty_stop_after_searches
            and latest_novel == 0
        ):
            action = "stop"
            reasons.append("no_novel_evidence_after_refinement")
        else:
            diverse_enough = (
                unique_source_count >= self.policy.target_diversity_count
                or unique_location_count >= self.policy.target_diversity_count
                or evidence_count >= self.policy.target_evidence_count
            )
            sufficient_count = evidence_count >= self.policy.minimum_stop_evidence_count
            if sufficient_count and diverse_enough and (
                not retrieval_fallback
                or evidence_count >= self.policy.target_evidence_count
            ):
                action = "stop"
                reasons.append("evidence_sufficient")
            elif retrieval_fallback and evidence_count <= 1:
                action = "retrieve"
                reasons.extend(("weak_evidence", "retrieval_fallback"))
            else:
                action = "refine"
                if evidence_count < self.policy.minimum_stop_evidence_count:
                    reasons.append("insufficient_evidence_count")
                if not diverse_enough:
                    reasons.append("insufficient_evidence_diversity")
                if retrieval_fallback:
                    reasons.append("retrieval_fallback")

        if latest_novel > 0:
            reasons.append("novel_evidence_found")

        return AgentEvidenceGateAssessment(
            action=action,  # type: ignore[arg-type]
            coverage_score=round(coverage_score, 4),
            diversity_score=round(diversity_score, 4),
            novelty_score=round(novelty_score, 4),
            quality_score=quality_score,
            evidence_count=evidence_count,
            unique_source_count=unique_source_count,
            unique_location_count=unique_location_count,
            novel_evidence_count=min(latest_novel, evidence_count),
            search_count=searches,
            remaining_searches=remaining,
            retrieval_fallback=retrieval_fallback,
            reason_codes=reasons,
        )


__all__ = ["AgentEvidenceGatePolicy", "AgentEvidenceGateService"]
