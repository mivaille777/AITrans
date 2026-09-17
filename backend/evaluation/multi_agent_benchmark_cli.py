from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from backend.evaluation.multi_agent_benchmark import (
    BenchmarkBudget,
    BenchmarkEnvironment,
    BenchmarkStrategy,
    load_multi_agent_evaluation_cases,
    run_multi_agent_benchmark,
    write_multi_agent_benchmark_report,
)
from backend.evaluation.multi_agent_benchmark_protocol import build_interleaved_schedule
from backend.evaluation.multi_agent_benchmark_recorded import RecordedBenchmarkRunner

_STRATEGIES: tuple[BenchmarkStrategy, ...] = (
    "single_agent",
    "legacy_collaboration",
    "multi_agent",
)


def _selected_cases(path: str, case_ids: Sequence[str]):
    cases = load_multi_agent_evaluation_cases(path)
    wanted = {item.strip() for item in case_ids if item.strip()}
    if not wanted:
        return cases
    selected = tuple(case for case in cases if case.case_id in wanted)
    missing = sorted(wanted - {case.case_id for case in selected})
    if missing:
        raise ValueError("unknown case ids: " + ", ".join(missing))
    return selected


def _load_budgets(path: str | Path) -> dict[BenchmarkStrategy, BenchmarkBudget]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("budget config must be a JSON object")
    budgets: dict[BenchmarkStrategy, BenchmarkBudget] = {}
    for strategy in _STRATEGIES:
        raw = payload.get(strategy)
        if not isinstance(raw, dict):
            raise ValueError(f"budget config is missing {strategy}")
        values = dict(raw)
        values.pop("mode", None)
        budgets[strategy] = BenchmarkBudget(mode="production", **values)
    return budgets


def _write_json(path: str | Path, payload: object) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AITrans MA10 benchmark protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule = subparsers.add_parser("schedule", help="write the randomized blind run schedule")
    schedule.add_argument("--cases", default="tests/multi_agent/evaluation_cases.json")
    schedule.add_argument("--case-id", action="append", default=[])
    schedule.add_argument("--repeats", type=int, default=3)
    schedule.add_argument("--seed", type=int, default=20260917)
    schedule.add_argument("--output", required=True)

    report = subparsers.add_parser("report", help="build a report from explicit recorded observations")
    report.add_argument("--cases", default="tests/multi_agent/evaluation_cases.json")
    report.add_argument("--case-id", action="append", default=[])
    report.add_argument("--observations", required=True)
    report.add_argument("--budgets", required=True)
    report.add_argument("--environment", choices=("deterministic", "qwen3_local", "configured_llm", "manual_ui"), required=True)
    report.add_argument("--equal-token-limit", type=int, required=True)
    report.add_argument("--unverified", action="append", default=[])
    report.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = _selected_cases(args.cases, args.case_id)
    if args.command == "schedule":
        schedule = build_interleaved_schedule(cases, repeats=args.repeats, seed=args.seed)
        _write_json(
            args.output,
            {
                "schema_version": "ma10-schedule-v1",
                "seed": args.seed,
                "repeats": args.repeats,
                "case_count": len(cases),
                "slots": [asdict(slot) for slot in schedule],
            },
        )
        return 0

    runner = RecordedBenchmarkRunner.from_json(args.observations)
    report = run_multi_agent_benchmark(
        cases,
        runner=runner,
        environment=args.environment,  # type: ignore[arg-type]
        production_budgets=_load_budgets(args.budgets),
        equal_token_limit=args.equal_token_limit,
        unverified_surfaces=tuple(args.unverified),
        metadata={"source": "recorded-observations"},
    )
    write_multi_agent_benchmark_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
