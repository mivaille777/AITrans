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
from backend.rag.benchmarks.qasper.loader import download_qasper_split, load_qasper
from backend.rag.benchmarks.qasper.runner import (
    RUN_LIMITS,
    GroundedQasperAnswerer,
    _profile_sha256,
    run_qasper_benchmark,
)
from backend.rag.config import RagConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the AITrans RAG baseline on QASPER known-paper QA."
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
    parser.add_argument("--run-id")
    parser.add_argument("--question-ids-file", type=Path)
    parser.add_argument("--config-json", type=Path)
    parser.add_argument(
        "--config-profile-id",
        help="Stable identifier recorded with --config-json; defaults to the profile file stem.",
    )
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = benchmark_root(args.root)
    raw_path = args.raw_json.expanduser().resolve() if args.raw_json else download_qasper_split(
        args.split,
        root / "raw",
        manifest_directory=root / "manifests",
    )
    dataset = load_qasper(raw_path, split=args.split)
    config_path = args.config_json.expanduser().resolve() if args.config_json else None
    config = (
        RagConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        if config_path is not None
        else RagConfig()
    )
    config_profile_id = (
        str(args.config_profile_id).strip()
        if args.config_profile_id
        else (config_path.stem if config_path is not None else "rag-default")
    )
    config_profile_sha256 = (
        _profile_sha256(config_path)
        if config_path is not None
        else None
    )
    answerer = None if args.retrieval_only else GroundedQasperAnswerer()
    try:
        result = run_qasper_benchmark(
            dataset,
            root=root,
            mode=args.mode,
            limit=args.limit,
            seed=args.seed,
            config=config,
            config_profile_id=config_profile_id,
            config_profile_sha256=config_profile_sha256,
            answerer=answerer,
            run_id=args.run_id,
            question_ids_file=args.question_ids_file,
            rebuild_index=args.rebuild_index,
        )
    finally:
        if answerer is not None:
            answerer.close()
    evaluation = evaluate_qasper_run(result.run_directory, root=root)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "status": result.run_status,
                "question_count": result.question_count,
                "error_count": result.error_count,
                "run_directory": str(result.run_directory),
                "manifest": str(result.manifest_path),
                "predictions": str(result.predictions_path),
                "retrieval_trace": str(result.retrieval_trace_path),
                "metrics": str(result.metrics_path),
                "official_answer_f1": evaluation["official_qasper"]["all_evidence"][
                    "Answer F1"
                ],
                "official_evidence_f1": evaluation["official_qasper"]["all_evidence"][
                    "Evidence F1"
                ],
                "errors": str(result.errors_path),
                "qrels": str(result.qrels_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.run_status == "complete" and result.error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
