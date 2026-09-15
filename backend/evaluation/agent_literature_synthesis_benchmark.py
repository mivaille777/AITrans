from __future__ import annotations

from typing import Any

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.citation_service import build_evidence_citations
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier
from backend.services.evidence_review_service import EvidenceReviewService

CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "accepted_supported_verified",
        "review": "accepted",
        "machine": "supported",
        "output": "The GP constrains the broad search region for PID tuning [1].",
        "expected": "agent",
    },
    {
        "case_id": "accepted_contested_verified",
        "review": "accepted",
        "machine": "contested",
        "output": "The studies disagree on the settling-time effect across evaluated conditions [1].",
        "expected": "agent",
    },
    {
        "case_id": "accepted_supported_missing_citation",
        "review": "accepted",
        "machine": "supported",
        "output": "The GP constrains the broad search region for PID tuning.",
        "expected": "deterministic_fallback",
    },
    {
        "case_id": "accepted_supported_unknown_citation",
        "review": "accepted",
        "machine": "supported",
        "output": "The GP constrains the broad search region for PID tuning [9].",
        "expected": "deterministic_fallback",
    },
    {
        "case_id": "accepted_stale_excluded",
        "review": "accepted",
        "machine": "stale",
        "output": "The GP constrains the broad search region for PID tuning [1].",
        "expected": "excluded",
    },
    {
        "case_id": "accepted_insufficient_excluded",
        "review": "accepted",
        "machine": "insufficient",
        "output": "The GP constrains the broad search region for PID tuning [1].",
        "expected": "excluded",
    },
    {
        "case_id": "rejected_supported_excluded",
        "review": "rejected",
        "machine": "supported",
        "output": "The GP constrains the broad search region for PID tuning [1].",
        "expected": "excluded",
    },
    {
        "case_id": "unreviewed_supported_excluded",
        "review": "unreviewed",
        "machine": "supported",
        "output": "The GP constrains the broad search region for PID tuning [1].",
        "expected": "excluded",
    },
)


def _mode(case: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    bucket, reason = EvidenceReviewService.synthesis_bucket(
        machine_status=str(case["machine"]),
        review_status=str(case["review"]),
    )
    if bucket == "excluded":
        return "excluded", {"bucket": bucket, "reason": reason}

    evidence = [
        AgentEvidenceItem(
            evidence_id="reviewed:test",
            source_type="research_memory",
            source_id="doc-1",
            title="Reviewed paper",
            location=f"{bucket} · supporting",
            excerpt=(
                "Review-gated ledger claim: The GP constrains the broad search region for PID tuning. "
                "The studies disagree on the settling-time effect across evaluated conditions."
            ),
            score=0.9,
            metadata={"rank": 1},
        )
    ]
    citations = build_evidence_citations(evidence)
    verification = AgentClaimEvidenceVerifier().verify(
        output_text=str(case["output"]),
        evidence=evidence,
        citations=citations,
    )
    mode = "agent" if verification.passed else "deterministic_fallback"
    return mode, {
        "bucket": bucket,
        "reason": reason,
        "verification_passed": verification.passed,
        "citation_coverage": verification.citation_coverage,
        "support_rate": verification.support_rate,
        "reason_codes": list(verification.reason_codes),
    }


def run_benchmark() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed = 0
    for case in CASES:
        actual, details = _mode(case)
        ok = actual == case["expected"]
        passed += int(ok)
        results.append(
            {
                "case_id": case["case_id"],
                "expected": case["expected"],
                "actual": actual,
                "passed": ok,
                **details,
            }
        )
    return {
        "stage": "20.1",
        "case_count": len(CASES),
        "passed": passed,
        "failed": len(CASES) - passed,
        "cases": results,
    }


__all__ = ["CASES", "run_benchmark"]
