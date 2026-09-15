from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from backend.evaluation.live_benchmark import (
    AgentLiveBenchmarkCase,
    AgentLiveBenchmarkSuite,
    run_live_benchmark,
)


def prepare_stage14_runtime_cases(
    cases: Iterable[AgentLiveBenchmarkCase],
) -> tuple[AgentLiveBenchmarkCase, ...]:
    """Give normal cases enough runtime headroom to reach a Final decision.

    ``AgentEvaluationExpectation.max_tool_calls`` and ``max_react_iterations``
    are assertions about the observed trajectory, not execution budgets. Using
    them as runtime budgets would incorrectly mark a trajectory that uses
    exactly N expected tools as exhausted before its final decision. Dedicated
    limit scenarios opt into strict runtime budgets through ``policy_max_*``
    fields, which are loaded into the case's explicit policy fields.
    """

    prepared: list[AgentLiveBenchmarkCase] = []
    for case in cases:
        if case.route_kind != "complex":
            prepared.append(case)
            continue
        tool_headroom = max(4, len(case.react_tool_sequence) + 1)
        iteration_headroom = max(4, len(case.react_tool_sequence) + 1)
        prepared.append(
            replace(
                case,
                max_tool_calls=case.max_tool_calls or tool_headroom,
                max_react_iterations=case.max_react_iterations or iteration_headroom,
            )
        )
    return tuple(prepared)


def run_stage14_suite(
    cases: Iterable[AgentLiveBenchmarkCase],
) -> AgentLiveBenchmarkSuite:
    return run_live_benchmark(prepare_stage14_runtime_cases(cases))


__all__ = ["prepare_stage14_runtime_cases", "run_stage14_suite"]
