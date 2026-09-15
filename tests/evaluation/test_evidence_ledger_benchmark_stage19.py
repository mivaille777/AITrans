from __future__ import annotations

from pathlib import Path

from backend.evaluation.evidence_ledger_benchmark import (
    run_stage19_evidence_ledger_benchmark,
)


DATASET = Path("backend/evaluation/datasets/stage19_evidence_ledger.jsonl")


def test_stage19_canonical_evidence_ledger_benchmark_is_complete_and_green() -> None:
    batch = run_stage19_evidence_ledger_benchmark(DATASET)

    assert batch.total_cases == 10
    assert batch.passed_cases == 10
    assert batch.pass_rate == 1.0
    assert any(item.supported_count > 0 for item in batch.results)
    assert any(item.contested_count > 0 for item in batch.results)
    assert any(item.insufficient_count > 0 for item in batch.results)
    assert any(item.stale_count > 0 for item in batch.results)
