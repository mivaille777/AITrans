from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.common import benchmark_root
from backend.rag.benchmarks.qasper.loader import download_qasper_split, load_qasper
from backend.rag.benchmarks.qasper.runner import (
    RUN_LIMITS,
    GroundedQasperAnswerer,
    run_qasper_raptor_ablation,
)
from backend.rag.config import RagConfig
from backend.rag.raptor import (
    ExtractiveRaptorSummaryProvider,
    LLMRaptorSummaryProvider,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the QASPER RAPTOR retrieval ablation matrix."
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
    parser.add_argument("--question-ids-file", type=Path)
    parser.add_argument("--suite-id")
    parser.add_argument("--variants", nargs="+", choices=("R0", "R1", "R2", "R3"))
    parser.add_argument(
        "--summary-provider",
        choices=("extractive", "llm"),
        default="extractive",
    )
    parser.add_argument("--config-json", type=Path)
    parser.add_argument(
        "--quality-profile",
        type=Path,
        default=(
            REPO_ROOT
            / "backend"
            / "rag"
            / "benchmarks"
            / "qasper"
            / "profiles"
            / "p1q1-evidence-selection-v2.json"
        ),
    )
    parser.add_argument(
        "--answer-contract",
        type=Path,
        default=(
            REPO_ROOT
            / "backend"
            / "rag"
            / "benchmarks"
            / "qasper"
            / "profiles"
            / "p1q2-direct-answer-v1.json"
        ),
    )
    parser.add_argument("--retrieval-only", action="store_true")
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
    config = (
        RagConfig.model_validate_json(args.config_json.read_text(encoding="utf-8"))
        if args.config_json
        else RagConfig()
    )
    profile_bytes = args.quality_profile.expanduser().resolve().read_bytes()
    quality_profile = json.loads(profile_bytes.decode("utf-8"))
    if not isinstance(quality_profile, dict):
        raise TypeError("quality profile JSON must contain an object")
    profile_sha256 = hashlib.sha256(profile_bytes).hexdigest()
    contract_bytes = args.answer_contract.expanduser().resolve().read_bytes()
    answer_contract = json.loads(contract_bytes.decode("utf-8"))
    if not isinstance(answer_contract, dict):
        raise TypeError("answer contract JSON must contain an object")
    answerer = (
        None
        if args.retrieval_only
        else GroundedQasperAnswerer(
            answer_contract=answer_contract,
            answer_contract_sha256=hashlib.sha256(contract_bytes).hexdigest(),
        )
    )
    summary_provider = (
        LLMRaptorSummaryProvider()
        if args.summary_provider == "llm"
        else ExtractiveRaptorSummaryProvider()
    )
    try:
        result = run_qasper_raptor_ablation(
            dataset,
            root=root,
            mode=args.mode,
            limit=args.limit,
            seed=args.seed,
            question_ids_file=args.question_ids_file,
            config=config,
            summary_provider=summary_provider,
            answerer=answerer,
            variants=args.variants or ("R0", "R1", "R2", "R3"),
            suite_id=args.suite_id,
            evidence_selection_variant="evidence_selection",
            quality_profile=quality_profile,
            quality_profile_sha256=profile_sha256,
        )
    finally:
        if answerer is not None:
            answerer.close()
        close_summary = getattr(summary_provider, "close", None)
        if callable(close_summary):
            close_summary()
    print(
        json.dumps(
            {
                "suite_id": result.suite_id,
                "status": result.status,
                "variant_count": result.variant_count,
                "tree_count": result.tree_count,
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
