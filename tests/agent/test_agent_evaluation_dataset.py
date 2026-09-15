from __future__ import annotations

from backend.evaluation.dataset import load_evaluation_dataset


def test_seed_agent_evaluation_dataset_loads() -> None:
    cases = load_evaluation_dataset("backend/evaluation/datasets/smoke.jsonl")

    assert [case.case_id for case in cases] == [
        "translate-selection",
        "explain-selection",
        "save-note-confirmation",
    ]
    assert cases[0].expected_tool_name == "translate_selection"
    assert cases[0].expected_tool_sequence == ("translate_selection",)
    assert cases[0].expect_react is False
    assert cases[0].max_tool_calls == 1
    assert cases[0].max_redundant_actions == 0
    assert cases[2].expected_status == "confirmation_required"
    assert cases[2].require_confirmation_guard is True
