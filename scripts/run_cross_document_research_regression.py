from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evaluation.cross_document_benchmark import (
    run_stage18_cross_document_benchmark,
)

DEFAULT_DATASET = "backend/evaluation/datasets/stage18_cross_document_research.jsonl"
DEFAULT_REPORT = "test-results/cross-document-research-regression.json"
EXPECTED_CANONICAL_CASES = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic Stage 18 multi-document Research Agent benchmark. "
            "The report stores aggregate metrics and case IDs only; raw research text "
            "and evidence excerpts are intentionally excluded."
        )
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch = run_stage18_cross_document_benchmark(args.dataset)
    canonical_dataset = Path(args.dataset).as_posix() == DEFAULT_DATASET
    expected_count_ok = (
        not canonical_dataset or batch.total_cases == EXPECTED_CANONICAL_CASES
    )
    passed = batch.total_cases > 0 and batch.pass_rate == 1.0 and expected_count_ok
    report = {
        "passed": passed,
        "protocol": "stage18.cross-document-research@1.0.0",
        "dataset": str(args.dataset),
        "expected_canonical_cases": (
            EXPECTED_CANONICAL_CASES if canonical_dataset else None
        ),
        "coverage_complete": expected_count_ok,
        "privacy": {
            "raw_note_text_in_report": False,
            "raw_claim_text_in_report": False,
            "raw_evidence_text_in_report": False,
            "document_urls_in_report": False,
        },
        "batch": asdict(batch),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
