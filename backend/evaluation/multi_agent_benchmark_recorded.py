from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

from backend.evaluation.multi_agent_benchmark import (
    BenchmarkBudget,
    BenchmarkObservation,
    BenchmarkStrategy,
    BenchmarkEnvironment,
    BenchmarkVersionInfo,
    MultiAgentBenchmarkCase,
)


class RecordedBenchmarkRunner:
    """Replay explicitly recorded benchmark observations without inventing gaps."""

    def __init__(self, observations: Mapping[tuple[str, str, str], BenchmarkObservation]) -> None:
        self._observations = dict(observations)

    @classmethod
    def from_json(cls, path: str | Path) -> "RecordedBenchmarkRunner":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_items = payload.get("observations", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise ValueError("recorded benchmark observations must be a JSON array")
        observations: dict[tuple[str, str, str], BenchmarkObservation] = {}
        allowed = {item.name for item in fields(BenchmarkObservation)}
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError("each recorded observation must be an object")
            case_id = str(raw.get("case_id", "") or "").strip()
            strategy = str(raw.get("strategy", "") or "").strip()
            budget_mode = str(raw.get("budget_mode", "") or "").strip()
            if not case_id or not strategy or not budget_mode:
                raise ValueError("recorded observation requires case_id, strategy, and budget_mode")
            key = (case_id, strategy, budget_mode)
            if key in observations:
                raise ValueError(f"duplicate recorded observation: {key}")
            values: dict[str, Any] = {name: raw[name] for name in allowed if name in raw}
            versions = values.get("versions")
            if isinstance(versions, dict):
                values["versions"] = BenchmarkVersionInfo(**versions)
            for tuple_field in ("degradation_reasons", "safety_violations"):
                if tuple_field in values:
                    values[tuple_field] = tuple(values[tuple_field] or ())
            observations[key] = BenchmarkObservation(**values)
        return cls(observations)

    def __call__(
        self,
        case: MultiAgentBenchmarkCase,
        *,
        strategy: BenchmarkStrategy,
        environment: BenchmarkEnvironment,
        budget: BenchmarkBudget,
    ) -> BenchmarkObservation:
        del environment
        key = (case.case_id, strategy, budget.mode)
        try:
            return self._observations[key]
        except KeyError as exc:
            raise ValueError(
                "missing recorded observation for "
                f"case={case.case_id}, strategy={strategy}, budget_mode={budget.mode}"
            ) from exc


__all__ = ["RecordedBenchmarkRunner"]
