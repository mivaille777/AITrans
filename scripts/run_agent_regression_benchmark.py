from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evaluation.dataset import load_evaluation_dataset
from backend.evaluation.live_benchmark import load_live_benchmark_cases
from backend.evaluation.quality_gate import (
    evaluate_regression_quality,
    load_quality_thresholds,
)
from backend.evaluation.regression_fixture import load_regression_fixture
from backend.evaluation.runner import AgentEvaluationBatchResult, evaluate_agent_batch
from backend.evaluation.stage14_suite import run_stage14_suite

DEFAULT_LIVE_DATASET = "backend/evaluation/datasets/stage14_live.jsonl"
DEFAULT_LIVE_THRESHOLDS = "backend/evaluation/datasets/stage14_quality_gate.json"
DEFAULT_LIVE_BASELINE = "backend/evaluation/datasets/stage14_baseline.json"
DEFAULT_FIXTURE_DATASET = "backend/evaluation/datasets/regression.jsonl"
DEFAULT_FIXTURE = "backend/evaluation/fixtures/regression_traces.json"
DEFAULT_FIXTURE_THRESHOLDS = "backend/evaluation/datasets/regression_quality_gate.json"
DEFAULT_REPORT = "test-results/agent-regression.json"
_HEADLINE_METRICS = (
    "pass_rate",
    "intent_accuracy",
    "tool_accuracy",
    "task_completion_rate",
    "fallback_rate",
    "tool_failure_rate",
    "retry_rate",
    "timeout_rate",
    "latency_p50_ms",
    "latency_p95_ms",
    "average_total_tokens",
    "grounded_rate",
    "grounding_verification_pass_rate",
    "confirmation_guard_rate",
    "redundant_action_rate",
    "react_limit_rate",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic Agent trajectory regression cases and fail when "
            "the configured quality gate is not satisfied. Live mode executes "
            "the production Agent graph with scripted deterministic boundaries."
        )
    )
    parser.add_argument("--mode", choices=("live", "fixture"), default="live")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--thresholds", default="")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    return parser.parse_args()


def _load_baseline(path: str) -> dict[str, float | int]:
    candidate = str(path or "").strip()
    if not candidate:
        return {}
    baseline_path = Path(candidate)
    if not baseline_path.exists():
        return {}
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Agent benchmark baseline must contain an object.")
    metrics = payload.get("metrics", payload)
    if not isinstance(metrics, dict):
        return {}
    result: dict[str, float | int] = {}
    for name in _HEADLINE_METRICS:
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[name] = value
    return result


def _regression_diff(
    batch: AgentEvaluationBatchResult,
    baseline: dict[str, float | int],
) -> dict[str, dict[str, float | int]]:
    diff: dict[str, dict[str, float | int]] = {}
    for name, previous in baseline.items():
        current = getattr(batch, name, None)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            continue
        diff[name] = {
            "baseline": previous,
            "current": current,
            "delta": round(float(current) - float(previous), 4),
        }
    return diff


def _run_live(dataset: str, thresholds_path: str):
    live_cases = load_live_benchmark_cases(dataset)
    suite = run_stage14_suite(live_cases)
    expectations = tuple(case.expectation for case in live_cases)
    batch = evaluate_agent_batch(
        expectations,
        resolve_run=lambda case: suite.get_run(case.case_id),
        resolve_events=suite.get_events,
    )
    quality = evaluate_regression_quality(batch, load_quality_thresholds(thresholds_path))
    return batch, quality, {
        "fixture_alignment_pass": True,
        "dataset_case_ids": [case.case_id for case in expectations],
        "fixture_case_ids": [],
        "category_counts": suite.category_counts,
    }


def _run_fixture(dataset: str, fixture_path: str, thresholds_path: str):
    cases = load_evaluation_dataset(dataset)
    fixture = load_regression_fixture(fixture_path)
    dataset_ids = tuple(case.case_id for case in cases)
    fixture_ids = tuple(case.case_id for case in fixture.cases)
    fixture_alignment_pass = dataset_ids == fixture_ids
    batch = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: fixture.get_run(case.case_id),
        resolve_events=fixture.get_events,
    )
    quality = evaluate_regression_quality(batch, load_quality_thresholds(thresholds_path))
    return batch, quality, {
        "fixture_alignment_pass": fixture_alignment_pass,
        "dataset_case_ids": list(dataset_ids),
        "fixture_case_ids": list(fixture_ids),
        "category_counts": {},
    }


def main() -> int:
    args = parse_args()
    if args.mode == "fixture":
        dataset = args.dataset or DEFAULT_FIXTURE_DATASET
        thresholds_path = args.thresholds or DEFAULT_FIXTURE_THRESHOLDS
        baseline_path = args.baseline
        batch, quality, metadata = _run_fixture(
            dataset,
            args.fixture,
            thresholds_path,
        )
    else:
        dataset = args.dataset or DEFAULT_LIVE_DATASET
        thresholds_path = args.thresholds or DEFAULT_LIVE_THRESHOLDS
        baseline_path = args.baseline or DEFAULT_LIVE_BASELINE
        batch, quality, metadata = _run_live(dataset, thresholds_path)

    baseline = _load_baseline(baseline_path)
    passed = bool(metadata["fixture_alignment_pass"]) and quality.passed
    report = {
        "passed": passed,
        "mode": args.mode,
        "dataset": str(dataset),
        "fixture": str(args.fixture) if args.mode == "fixture" else "",
        "thresholds": str(thresholds_path),
        "baseline": str(baseline_path or ""),
        **metadata,
        "regression_diff": _regression_diff(batch, baseline),
        "quality_gate": asdict(quality),
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
