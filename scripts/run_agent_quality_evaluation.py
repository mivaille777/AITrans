from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evaluation.qualitative import (
    AgentQualityJudgement,
    load_human_reviews,
    load_quality_samples,
    resolve_quality_batch,
)
from backend.services.agent_quality_judge_service import AgentQualityJudgeService

DEFAULT_DATASET = "backend/evaluation/datasets/stage15_quality_smoke.jsonl"
DEFAULT_REPORT = "outputs/agent-quality-report.json"
DEFAULT_JUDGEMENTS = "outputs/agent-quality-judgements.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Stage 15 offline qualitative Agent evaluation protocol. "
            "By default this invokes the configured AI provider as a structured "
            "judge. Supplying --judgements replays a saved score-only judge file "
            "without making provider calls."
        )
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--judgements", default="")
    parser.add_argument("--reviews", default="")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--save-judgements", default=DEFAULT_JUDGEMENTS)
    parser.add_argument(
        "--require-resolved",
        action="store_true",
        help="Exit non-zero while any final case verdict remains review.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.0,
        help=(
            "Optional informational gate for manual/controlled evaluation runs. "
            "This is not used by the deterministic merge CI."
        ),
    )
    return parser.parse_args()


def _load_judgements(path: str | Path) -> tuple[AgentQualityJudgement, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Saved qualitative judgements must contain a JSON list.")
    judgements = tuple(AgentQualityJudgement.model_validate(item) for item in payload)
    case_ids = [item.case_id for item in judgements]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Saved qualitative judgements contain duplicate case_id values.")
    return judgements


def _write_judgements(
    path: str | Path,
    judgements: tuple[AgentQualityJudgement, ...],
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in judgements],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _alignment_failures(
    sample_ids: tuple[str, ...],
    judgement_ids: tuple[str, ...],
    review_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    failures: list[str] = []
    if len(judgement_ids) != len(set(judgement_ids)):
        failures.append("duplicate judgement case_id")
    missing = sorted(set(sample_ids) - set(judgement_ids))
    extra = sorted(set(judgement_ids) - set(sample_ids))
    unknown_reviews = sorted(set(review_ids) - set(sample_ids))
    if missing:
        failures.append("missing judgements: " + ", ".join(missing))
    if extra:
        failures.append("unknown judgements: " + ", ".join(extra))
    if unknown_reviews:
        failures.append("unknown human reviews: " + ", ".join(unknown_reviews))
    return tuple(failures)


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.min_pass_rate <= 1.0:
        raise ValueError("--min-pass-rate must be between 0 and 1.")

    samples = load_quality_samples(args.dataset)
    sample_ids = tuple(sample.case_id for sample in samples)
    judge_service: AgentQualityJudgeService | None = None

    if args.judgements:
        judgements = _load_judgements(args.judgements)
        mode = "replay"
    else:
        mode = "judge"
        judge_service = AgentQualityJudgeService()
        try:
            judgements = tuple(judge_service.judge(sample) for sample in samples)
        finally:
            judge_service.close()
        if args.save_judgements:
            _write_judgements(args.save_judgements, judgements)

    judgement_ids = tuple(item.case_id for item in judgements)
    human_reviews = load_human_reviews(args.reviews) if args.reviews else {}
    review_ids = tuple(human_reviews)
    alignment_failures = _alignment_failures(
        sample_ids,
        judgement_ids,
        review_ids,
    )
    batch = resolve_quality_batch(judgements, human_reviews=human_reviews)
    pending_review_ids = [
        item.case_id
        for item in batch.results
        if item.needs_human_review or item.final_verdict == "review"
    ]
    unmatched_review_ids = sorted(set(review_ids) - set(sample_ids))

    passed = not alignment_failures
    if args.require_resolved and pending_review_ids:
        passed = False
    if args.min_pass_rate > 0 and batch.pass_rate < args.min_pass_rate:
        passed = False

    report = {
        "passed": passed,
        "protocol": "stage15.qualitative@1.0.0",
        "mode": mode,
        "dataset": str(args.dataset),
        "judgements": str(args.judgements or args.save_judgements or ""),
        "reviews": str(args.reviews or ""),
        "privacy": {
            "raw_task_in_report": False,
            "raw_response_in_report": False,
            "raw_evidence_in_report": False,
            "private_reasoning_in_report": False,
        },
        "alignment_failures": list(alignment_failures),
        "pending_human_review_case_ids": pending_review_ids,
        "unmatched_human_review_case_ids": unmatched_review_ids,
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
