from __future__ import annotations

from collections import Counter

import pytest

from backend.evaluation.multi_agent_benchmark import MultiAgentBenchmarkCase
from backend.evaluation.multi_agent_benchmark_protocol import build_interleaved_schedule


def _cases():
    return (
        MultiAgentBenchmarkCase(
            case_id="T35",
            split="heldout",
            stages=("MA10",),
            category="ab_evaluation",
            prompt="compare",
            fixture_refs=(),
            hard_assertions=("report all metrics",),
            score_dimensions=("completion", "latency", "cost"),
        ),
        MultiAgentBenchmarkCase(
            case_id="T05",
            split="dev",
            stages=("MA04",),
            category="comparison",
            prompt="compare papers",
            fixture_refs=("paper-a", "paper-b"),
            hard_assertions=("conditions retained",),
            score_dimensions=("completion", "source_support"),
        ),
    )


def test_schedule_is_reproducible_and_interleaves_all_strategies() -> None:
    first = build_interleaved_schedule(_cases(), repeats=3, seed=42)
    second = build_interleaved_schedule(_cases(), repeats=3, seed=42)

    assert first == second
    assert len(first) == 2 * 3 * 2 * 3
    counts = Counter((slot.case_id, slot.strategy, slot.budget_mode) for slot in first)
    assert set(counts.values()) == {3}
    assert len({slot.blind_id for slot in first}) == len(first)
    assert {slot.strategy for slot in first[:6]} != {"single_agent"}


def test_different_seed_changes_order_not_membership() -> None:
    first = build_interleaved_schedule(_cases(), repeats=3, seed=1)
    second = build_interleaved_schedule(_cases(), repeats=3, seed=2)

    assert [slot.blind_id for slot in first] != [slot.blind_id for slot in second]
    assert Counter((slot.case_id, slot.strategy, slot.budget_mode, slot.repeat) for slot in first) == Counter(
        (slot.case_id, slot.strategy, slot.budget_mode, slot.repeat) for slot in second
    )


def test_schedule_requires_positive_repeats() -> None:
    with pytest.raises(ValueError, match="repeats"):
        build_interleaved_schedule(_cases(), repeats=0)
