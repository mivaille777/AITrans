from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.evaluation.qualitative import (
    AgentHumanReview,
    AgentQualityJudgement,
    load_human_reviews,
    load_quality_samples,
    resolve_quality_batch,
)
from scripts.run_agent_quality_evaluation import _alignment_failures

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "backend/evaluation/datasets/stage15_quality_smoke.jsonl"
JUDGEMENTS = REPO_ROOT / "backend/evaluation/fixtures/stage15_quality_judgements.json"
REVIEWS = REPO_ROOT / "backend/evaluation/fixtures/stage15_human_reviews.json"


def _fixture_judgements() -> tuple[AgentQualityJudgement, ...]:
    payload = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))
    return tuple(AgentQualityJudgement.model_validate(item) for item in payload)


def test_stage15_smoke_dataset_and_replay_fixture_are_aligned() -> None:
    samples = load_quality_samples(DATASET)
    judgements = _fixture_judgements()

    assert len(samples) == 12
    assert {sample.case_id for sample in samples} == {
        judgement.case_id for judgement in judgements
    }
    assert all(sample.synthetic for sample in samples)
    assert {
        "translation",
        "reading",
        "summarization",
        "research",
        "prompt_injection",
        "safety",
    }.issubset({sample.category for sample in samples})


def test_replay_fixture_reports_judge_and_human_review_rates_separately() -> None:
    judgements = _fixture_judgements()
    reviews = load_human_reviews(REVIEWS)

    batch = resolve_quality_batch(judgements, human_reviews=reviews)

    assert batch.total_cases == 12
    assert batch.judge_pass_rate == 0.6667
    assert batch.judge_review_rate == 0.0833
    assert batch.judge_fail_rate == 0.25
    assert batch.pass_rate == 0.6667
    assert batch.review_cases == 0
    assert batch.failed_cases == 4
    assert batch.human_reviewed_rate == 0.0833
    assert batch.pending_human_review_rate == 0.0
    assert batch.human_override_rate == 0.0833
    assert batch.human_agreement_rate == 0.0


def test_saved_judgement_cannot_claim_pass_when_scores_imply_fail() -> None:
    payload = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))[0]
    payload["verdict"] = "pass"
    for dimension in payload["dimensions"]:
        if dimension["name"] == "safety":
            dimension["score"] = 1

    with pytest.raises(ValueError, match="inconsistent with deterministic rubric policy"):
        AgentQualityJudgement.model_validate(payload)


def test_saved_judgement_cannot_claim_pass_when_major_completeness_issue_requires_review() -> None:
    payload = json.loads(JUDGEMENTS.read_text(encoding="utf-8"))[0]
    payload["verdict"] = "pass"
    for dimension in payload["dimensions"]:
        if dimension["name"] == "completeness":
            dimension["score"] = 2

    with pytest.raises(ValueError, match="inconsistent with deterministic rubric policy"):
        AgentQualityJudgement.model_validate(payload)


def test_human_review_may_remain_explicitly_unresolved() -> None:
    judgement = next(
        item for item in _fixture_judgements() if item.case_id == "quality-incomplete-answer"
    )
    review = AgentHumanReview(
        case_id=judgement.case_id,
        verdict="review",
        reviewer="reviewer-1",
        reason_codes=["needs_domain_expert"],
    )

    batch = resolve_quality_batch(
        (judgement,),
        human_reviews={judgement.case_id: review},
    )

    assert batch.review_cases == 1
    assert batch.results[0].human_reviewed is True
    assert batch.results[0].needs_human_review is False
    assert batch.results[0].final_verdict == "review"


def test_alignment_rejects_human_reviews_for_unknown_cases() -> None:
    failures = _alignment_failures(
        ("known",),
        ("known",),
        ("known", "unknown-review"),
    )

    assert failures == ("unknown human reviews: unknown-review",)
