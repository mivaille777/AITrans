from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.performance import (
    RagPerformanceCandidate,
    compare_performance_candidates,
    performance_sweeps,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare one-factor RAG performance runs with quality gates."
    )
    parser.add_argument(
        "--list-variants",
        action="store_true",
        help="print the controlled benchmark matrix and exit",
    )
    parser.add_argument("--baseline", default="", help="Baseline result JSON path.")
    parser.add_argument("--candidate", default="", help="Candidate result JSON path.")
    parser.add_argument("--max-recall-drop", type=float, default=0.02)
    parser.add_argument("--max-ndcg-drop", type=float, default=0.02)
    return parser.parse_args()


def _candidate(path: str) -> RagPerformanceCandidate:
    return RagPerformanceCandidate.model_validate_json(
        Path(path).read_text(encoding="utf-8-sig")
    )


def main() -> int:
    args = parse_args()
    if args.list_variants:
        payload = {
            key: [item.model_dump(mode="json") for item in values]
            for key, values in performance_sweeps().items()
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not args.baseline or not args.candidate:
        raise SystemExit("--baseline and --candidate are required for comparison")
    comparison = compare_performance_candidates(
        _candidate(args.baseline),
        _candidate(args.candidate),
        max_recall_drop=args.max_recall_drop,
        max_ndcg_drop=args.max_ndcg_drop,
    )
    print(
        json.dumps(
            comparison.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if comparison.eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
