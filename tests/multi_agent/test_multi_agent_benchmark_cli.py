from __future__ import annotations

import json
from pathlib import Path

from backend.evaluation.multi_agent_benchmark_cli import main


def test_cli_writes_three_repeat_interleaved_schedule(tmp_path: Path) -> None:
    output = tmp_path / "schedule.json"
    assert main(
        [
            "schedule",
            "--case-id",
            "T35",
            "--repeats",
            "3",
            "--seed",
            "7",
            "--output",
            str(output),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "ma10-schedule-v1"
    assert payload["case_count"] == 1
    assert len(payload["slots"]) == 18
    assert len({item["blind_id"] for item in payload["slots"]}) == 18


def test_cli_builds_report_only_from_explicit_observations(tmp_path: Path) -> None:
    observations = tmp_path / "observations.json"
    rows = []
    assertions = ["quality cost latency all reported", "no benefit claim based on role count"]
    for strategy in ("single_agent", "legacy_collaboration", "multi_agent"):
        for mode in ("production", "equal_token"):
            rows.append(
                {
                    "case_id": "T35",
                    "strategy": strategy,
                    "budget_mode": mode,
                    "completed": True,
                    "hard_assertion_results": {item: True for item in assertions},
                    "dimension_scores": {"completion": 1.0, "source_support": 1.0, "latency": 0.8, "cost": 0.8},
                    "source_coverage": 1.0,
                    "prompt_tokens": 50,
                    "completion_tokens": 20,
                    "model_calls": 1,
                    "tool_calls": 1,
                    "latency_ms": 10,
                }
            )
    observations.write_text(json.dumps(rows), encoding="utf-8")

    budgets = tmp_path / "budgets.json"
    budgets.write_text(
        json.dumps(
            {
                strategy: {
                    "token_limit": 100,
                    "model_call_limit": 2,
                    "tool_call_limit": 3,
                    "retrieval_call_limit": 2,
                    "deadline_ms": 1000,
                }
                for strategy in ("single_agent", "legacy_collaboration", "multi_agent")
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    assert main(
        [
            "report",
            "--case-id",
            "T35",
            "--observations",
            str(observations),
            "--budgets",
            str(budgets),
            "--environment",
            "deterministic",
            "--equal-token-limit",
            "100",
            "--output",
            str(output),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_count"] == 1
    assert len(payload["tasks"]) == 6
    assert payload["release_ready"] is True
