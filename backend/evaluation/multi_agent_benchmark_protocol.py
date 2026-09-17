from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

from backend.evaluation.multi_agent_benchmark import (
    BenchmarkBudgetMode,
    BenchmarkStrategy,
    MultiAgentBenchmarkCase,
)


@dataclass(frozen=True, slots=True)
class BenchmarkRunSlot:
    sequence: int
    case_id: str
    strategy: BenchmarkStrategy
    budget_mode: BenchmarkBudgetMode
    repeat: int
    blind_id: str


def _blind_id(case_id: str, strategy: str, budget_mode: str, repeat: int, seed: int) -> str:
    material = f"{seed}\0{case_id}\0{strategy}\0{budget_mode}\0{repeat}".encode()
    return "blind-" + hashlib.sha256(material).hexdigest()[:12]


def build_interleaved_schedule(
    cases: Iterable[MultiAgentBenchmarkCase],
    *,
    strategies: Sequence[BenchmarkStrategy] = (
        "single_agent",
        "legacy_collaboration",
        "multi_agent",
    ),
    budget_modes: Sequence[BenchmarkBudgetMode] = ("production", "equal_token"),
    repeats: int = 3,
    seed: int = 20260917,
) -> tuple[BenchmarkRunSlot, ...]:
    frozen_cases = tuple(cases)
    if not frozen_cases:
        raise ValueError("benchmark schedule requires at least one case")
    if repeats < 1:
        raise ValueError("benchmark schedule repeats must be >= 1")
    raw: list[tuple[str, BenchmarkStrategy, BenchmarkBudgetMode, int, str]] = []
    for case in frozen_cases:
        for repeat in range(1, repeats + 1):
            for budget_mode in budget_modes:
                for strategy in strategies:
                    raw.append(
                        (
                            case.case_id,
                            strategy,
                            budget_mode,
                            repeat,
                            _blind_id(case.case_id, strategy, budget_mode, repeat, seed),
                        )
                    )
    random.Random(seed).shuffle(raw)
    return tuple(
        BenchmarkRunSlot(
            sequence=index,
            case_id=case_id,
            strategy=strategy,
            budget_mode=budget_mode,
            repeat=repeat,
            blind_id=blind_id,
        )
        for index, (case_id, strategy, budget_mode, repeat, blind_id) in enumerate(raw, start=1)
    )


__all__ = ["BenchmarkRunSlot", "build_interleaved_schedule"]
