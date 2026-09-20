from pathlib import Path

from backend.evaluation.multi_agent_contract_matrix import (
    load_contract_evidence,
    validate_contract_evidence,
)


def test_contract_evidence_covers_every_frozen_t01_t36_case() -> None:
    root = Path(__file__).resolve().parents[2]
    case_ids = validate_contract_evidence(
        cases_path=root / "tests" / "multi_agent" / "evaluation_cases.json",
        evidence_path=root / "tests" / "multi_agent" / "evaluation_evidence.json",
    )

    assert case_ids == tuple(f"T{index:02d}" for index in range(1, 37))


def test_contract_evidence_uses_explicit_test_selectors() -> None:
    root = Path(__file__).resolve().parents[2]
    evidence = load_contract_evidence(
        root / "tests" / "multi_agent" / "evaluation_evidence.json"
    )

    assert all(
        "::test_" in selector
        for item in evidence.values()
        for selector in item["pytest"]
    )
    assert evidence["T28"]["vitest"] == (
        "src/features/agent/runtime/agent-event-replay.test.ts",
    )
