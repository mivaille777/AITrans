from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evaluation.research_memory_benchmark import (
    run_stage17_3_research_memory_benchmark,
)

DEFAULT_DATASET = "backend/evaluation/datasets/stage17_3_research_memory.jsonl"
DEFAULT_REPORT = "test-results/research-memory-regression.json"
EXPECTED_CANONICAL_CASES = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic Stage 17.3 structured Research Memory reliability "
            "benchmark. The report contains aggregate reliability metrics and case IDs "
            "only; raw note, claim and evidence text is intentionally excluded."
        )
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch = run_stage17_3_research_memory_benchmark(args.dataset)
    canonical_dataset = Path(args.dataset).as_posix() == Path(DEFAULT_DATASET).as_posix()
    coverage_pass = (
        batch.total_cases == EXPECTED_CANONICAL_CASES
        if canonical_dataset
        else batch.total_cases > 0
    )
    passed = coverage_pass and batch.pass_rate == 1.0
    report = {
        "passed": passed,
        "protocol": "stage17.3.research-memory-reliability@1.0.0",
        "dataset": str(args.dataset),
        "coverage": {
            "canonical_dataset": canonical_dataset,
            "expected_cases": EXPECTED_CANONICAL_CASES if canonical_dataset else None,
            "actual_cases": batch.total_cases,
            "passed": coverage_pass,
        },
        "privacy": {
            "raw_note_text_in_report": False,
            "raw_claim_text_in_report": False,
            "raw_evidence_text_in_report": False,
            "entity_descriptions_in_report": False,
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
