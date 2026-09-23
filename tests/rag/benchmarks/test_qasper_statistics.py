from __future__ import annotations

import pytest

from backend.rag.benchmarks.qasper.statistics import paired_bootstrap


def test_paired_bootstrap_reports_deterministic_candidate_deltas_and_ci() -> None:
    baseline = [
        {
            "question_id": "q1",
            "official_answer_f1": 0.0,
            "official_evidence_f1": 0.5,
            "gold_evidence_recall_at_10": 0.5,
            "MRR": 0.5,
        },
        {
            "question_id": "q2",
            "official_answer_f1": 0.5,
            "official_evidence_f1": 0.0,
            "gold_evidence_recall_at_10": 0.0,
            "MRR": 0.0,
        },
        {
            "question_id": "q3",
            "official_answer_f1": 1.0,
            "official_evidence_f1": 1.0,
            "gold_evidence_recall_at_10": 1.0,
            "MRR": 1.0,
        },
    ]
    candidate = [
        {
            "question_id": "q1",
            "official_answer_f1": 0.5,
            "official_evidence_f1": 1.0,
            "gold_evidence_recall_at_10": 1.0,
            "MRR": 1.0,
        },
        {
            "question_id": "q2",
            "official_answer_f1": 0.5,
            "official_evidence_f1": 0.5,
            "gold_evidence_recall_at_10": 0.5,
            "MRR": 0.5,
        },
        {
            "question_id": "q3",
            "official_answer_f1": 1.0,
            "official_evidence_f1": 1.0,
            "gold_evidence_recall_at_10": 1.0,
            "MRR": 1.0,
        },
        {"question_id": "unpaired", "official_answer_f1": 0.0},
    ]

    result = paired_bootstrap(baseline, candidate, seed=7, resamples=500)
    repeated = paired_bootstrap(baseline, candidate, seed=7, resamples=500)

    assert result == repeated
    assert result["paired_question_count"] == 3
    assert result["question_ids"] == ["q1", "q2", "q3"]
    assert result["metrics"]["Answer F1"]["paired_count"] == 3
    assert result["metrics"]["Answer F1"]["delta"] == pytest.approx(1 / 6)
    assert result["metrics"]["Evidence F1"]["delta"] == pytest.approx(1 / 3)
    assert result["metrics"]["Recall@10"]["delta"] == pytest.approx(1 / 3)
    assert (
        result["metrics"]["MRR"]["ci_95"]["lower"] <= result["metrics"]["MRR"]["delta"]
    )
    assert (
        result["metrics"]["MRR"]["delta"] <= result["metrics"]["MRR"]["ci_95"]["upper"]
    )


def test_paired_bootstrap_requires_common_question_ids() -> None:
    with pytest.raises(ValueError, match="paired questions"):
        paired_bootstrap(
            [{"question_id": "baseline"}],
            [{"question_id": "candidate"}],
            resamples=100,
        )
