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
    parser.add_argument("--question-ids-file", type=Path)
    parser.add_argument("--suite-id")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=("one_shot", "multi_query", "evidence_gated", "requirement_aware"),
        default=None,
    )
    parser.add_argument(
        "--quality-profile",
        type=Path,
        help="Versioned evidence-selection profile to apply to each adaptive variant.",
    )
    parser.add_argument(
        "--evidence-selection-variant",
        choices=(
            "current_top20",
            "rerank_top5",
            "rerank_top8",
            "rerank_top10",
            "evidence_selection",
            "raw_top_k",
            "rerank_top_k",
        ),
        help="Selected-evidence policy; supports one_shot and requirement_aware ablations.",
    )
    parser.add_argument(
        "--answer-contract",
        type=Path,
        help="Versioned JSON answer contract; omitted uses the legacy answer prompt.",
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
    selected_variants = args.variants or (
        ("one_shot", "requirement_aware")
        if args.evidence_selection_variant
        else ("one_shot", "multi_query", "evidence_gated", "requirement_aware")
    )
    quality_profile = None
    quality_profile_sha256 = None
    if args.evidence_selection_variant:
        if args.quality_profile is None:
            raise ValueError("--quality-profile is required with --evidence-selection-variant")
        profile_bytes = args.quality_profile.expanduser().resolve().read_bytes()
        quality_profile = json.loads(profile_bytes.decode("utf-8"))
        if not isinstance(quality_profile, dict):
            raise TypeError("quality profile JSON must contain an object")
        quality_profile_sha256 = hashlib.sha256(profile_bytes).hexdigest()
    answer_contract = None
    answer_contract_sha256 = None
    if args.answer_contract is not None:
        contract_bytes = args.answer_contract.expanduser().resolve().read_bytes()
        answer_contract = json.loads(contract_bytes.decode("utf-8"))
        if not isinstance(answer_contract, dict):
            raise TypeError("answer contract JSON must contain an object")
        answer_contract_sha256 = hashlib.sha256(contract_bytes).hexdigest()
    answerer = (
        None
        if args.retrieval_only
        else GroundedQasperAnswerer(
            answer_contract=answer_contract,
            answer_contract_sha256=answer_contract_sha256,
        )
    )
    query_planner = (
        build_rag_query_planner()
        if set(selected_variants).intersection(
            {"multi_query", "evidence_gated", "requirement_aware"}
        )
        else None
    )
    try:
        result = run_qasper_adaptive_retrieval_ablation(
            dataset,
            root=root,
            mode=args.mode,
            limit=args.limit,
            seed=args.seed,
            question_ids_file=args.question_ids_file,
            config=config,
            variants=selected_variants,
            answerer=answerer,
            query_planner=query_planner,
            suite_id=args.suite_id,
            evidence_selection_variant=args.evidence_selection_variant,
            quality_profile=quality_profile,
            quality_profile_sha256=quality_profile_sha256,
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
                "evidence_selection_variant": args.evidence_selection_variant,
                "quality_profile": (
                    str(args.quality_profile.expanduser().resolve())
                    if args.quality_profile
                    else None
                ),
                "quality_profile_sha256": quality_profile_sha256,
                "answer_contract": (
                    str(args.answer_contract.expanduser().resolve())
                    if args.answer_contract
                    else None
                ),
                "answer_contract_sha256": answer_contract_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
