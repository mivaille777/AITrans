from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.api.llm_dependencies import build_rag_query_planner
from backend.rag.benchmarks.common import benchmark_root
from backend.rag.benchmarks.qasper.loader import download_qasper_split, load_qasper
from backend.rag.benchmarks.qasper.runner import (
    RUN_LIMITS,
    GroundedQasperAnswerer,
    run_qasper_adaptive_retrieval_ablation,
)
from backend.rag.config import RagConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the QASPER adaptive-retrieval ablation matrix."
    )
    parser.add_argument("--root", type=Path, default=Path("data/benchmarks/qasper"))
    parser.add_argument(
        "--split",
        choices=("validation", "dev", "train"),
        default="validation",
    )
    parser.add_argument("--raw-json", type=Path)
    parser.add_argument("--mode", choices=tuple(RUN_LIMITS), default="smoke")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--suite-id")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=("one_shot", "multi_query", "evidence_gated", "requirement_aware"),
        default=("one_shot", "multi_query", "evidence_gated", "requirement_aware"),
    )
    parser.add_argument("--config-json", type=Path)
    parser.add_argument("--retrieval-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = benchmark_root(args.root)
    raw_path = (
        args.raw_json.expanduser().resolve()
        if args.raw_json
        else download_qasper_split(
            args.split,
            root / "raw",
            manifest_directory=root / "manifests",
        )
    )
    dataset = load_qasper(raw_path, split=args.split)
    config = (
        RagConfig.model_validate_json(args.config_json.read_text(encoding="utf-8"))
        if args.config_json
        else RagConfig()
    )
    answerer = None if args.retrieval_only else GroundedQasperAnswerer()
    query_planner = (
        build_rag_query_planner()
        if set(args.variants).intersection({"multi_query", "evidence_gated"})
        else None
    )
    try:
        result = run_qasper_adaptive_retrieval_ablation(
            dataset,
            root=root,
            mode=args.mode,
            limit=args.limit,
            seed=args.seed,
            config=config,
            variants=args.variants,
            answerer=answerer,
            query_planner=query_planner,
            suite_id=args.suite_id,
        )
    finally:
        if answerer is not None:
            answerer.close()
        planner_text_service = getattr(query_planner, "_text_service", None)
        close_planner = getattr(planner_text_service, "close", None)
        if callable(close_planner):
            close_planner()

    print(
        json.dumps(
            {
                "suite_id": result.suite_id,
                "status": result.status,
                "variant_count": result.variant_count,
                "suite_directory": str(result.suite_directory),
                "manifest": str(result.manifest_path),
                "comparison": str(result.comparison_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
