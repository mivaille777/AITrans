from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.services.evidence_review_service import EvidenceReviewService

DEFAULT_DATASET = Path(__file__).with_name("datasets") / "stage20_evidence_review.jsonl"


def load_cases(path: str | Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run_benchmark(path: str | Path = DEFAULT_DATASET) -> dict[str, Any]:
    cases = load_cases(path)
    failures: list[dict[str, str]] = []
    for case in cases:
        bucket, reason = EvidenceReviewService.synthesis_bucket(
            machine_status=str(case["machine_status"]),
            review_status=str(case["review_status"]),
        )
        if bucket != case["expected_bucket"] or reason != case["expected_reason"]:
            failures.append(
                {
                    "case_id": str(case["case_id"]),
                    "expected": f"{case['expected_bucket']}:{case['expected_reason']}",
                    "actual": f"{bucket}:{reason}",
                }
            )
    return {
        "stage": 20,
        "benchmark": "evidence_review_and_synthesis",
        "case_count": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }


__all__ = ["DEFAULT_DATASET", "load_cases", "run_benchmark"]
