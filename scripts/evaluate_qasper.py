from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.common import benchmark_root
from backend.rag.benchmarks.qasper.evaluator import evaluate_qasper_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval and answer metrics for an AITrans QASPER run."
    )
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/benchmarks/qasper"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    metrics = evaluate_qasper_run(
        args.run_directory,
        root=benchmark_root(args.root),
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
