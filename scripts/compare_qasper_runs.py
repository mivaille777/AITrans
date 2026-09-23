from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.qasper.protocol import (
    compare_qasper_runs,
    write_comparison_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strictly compare paired QASPER runs and calculate bootstrap CIs."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        comparison = compare_qasper_runs(
            args.baseline,
            args.candidate,
            resamples=args.resamples,
            seed=args.seed,
        )
        report_path = write_comparison_report(comparison, args.candidate)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"QASPER run comparison failed: {exc}", file=sys.stderr)
        return 2
    comparison["report_path"] = str(report_path)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
