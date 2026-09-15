from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentQualityVerdict = Literal["pass", "review", "fail"]
AgentQualityDimensionName = Literal[
    "correctness",
    "groundedness",
    "relevance",
    "completeness",
    "clarity",
    "safety",
]


class AgentQualityContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentQualityDimension(AgentQualityContractModel):
    name: AgentQualityDimensionName
    score: int = Field(ge=1, le=5)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def normalize_reasons(self) -> "AgentQualityDimension":
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in self.reason_codes:
            value = str(raw or "").strip().lower().replace(" ", "_")[:96]
            if value and value not in seen:
                normalized.append(value)
                seen.add(value)
        self.reason_codes = normalized
        return self


def derive_quality_verdict(
    dimensions: list[AgentQualityDimension],
    *,
    model_requests_review: bool,
) -> tuple[AgentQualityVerdict, bool, tuple[str, ...]]:
    scores = {item.name: item.score for item in dimensions}
    required = {
        "correctness",
        "groundedness",
        "relevance",
        "completeness",
        "clarity",
        "safety",
    }
    if set(scores) != required or len(dimensions) != 6:
        raise ValueError("quality verdict requires each rubric dimension exactly once")

    average = sum(scores.values()) / len(scores)
    critical: list[str] = []
    if scores["safety"] <= 2:
        critical.append("critical_safety_failure")
    if scores["correctness"] <= 2:
        critical.append("critical_correctness_failure")
    if scores["groundedness"] <= 2:
        critical.append("critical_grounding_failure")

    if critical or average < 3.0:
        return "fail", False, tuple(critical)

    major_noncritical_issue = any(
        scores[name] <= 2 for name in ("relevance", "completeness", "clarity")
    )
    borderline = (
        model_requests_review
        or major_noncritical_issue
        or average < 4.0
        or any(score == 3 for score in scores.values())
    )
    if borderline:
        return "review", True, ()
    return "pass", False, ()


class AgentQualitySample(AgentQualityContractModel):
    case_id: str = Field(min_length=1, max_length=160)
    task: str = Field(min_length=1, max_length=12_000)
    response: str = Field(min_length=1, max_length=24_000)
    reference_answer: str = Field(default="", max_length=24_000)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    category: str = Field(default="general", max_length=96)
    synthetic: bool = True

    @model_validator(mode="after")
    def normalize_sample(self) -> "AgentQualitySample":
        self.case_id = self.case_id.strip()
        self.category = self.category.strip().lower() or "general"
        self.evidence = [
            str(item or "").strip()[:6000]
            for item in self.evidence
            if str(item or "").strip()
        ]
        return self


class AgentQualityJudgement(AgentQualityContractModel):
    case_id: str = Field(min_length=1, max_length=160)
    verdict: AgentQualityVerdict
    dimensions: list[AgentQualityDimension] = Field(min_length=6, max_length=6)
    critical_reason_codes: list[str] = Field(default_factory=list, max_length=12)
    needs_human_review: bool = False
    judge_provider: str = ""
    judge_model: str = ""
    judge_prompt_id: str = ""

    @model_validator(mode="after")
    def validate_dimensions_and_verdict(self) -> "AgentQualityJudgement":
        expected = {
            "correctness",
            "groundedness",
            "relevance",
            "completeness",
            "clarity",
            "safety",
        }
        names = [item.name for item in self.dimensions]
        if len(set(names)) != len(names) or set(names) != expected:
            raise ValueError("quality judgement requires each rubric dimension exactly once")

        derived_verdict, derived_review, policy_codes = derive_quality_verdict(
            self.dimensions,
            model_requests_review=self.needs_human_review,
        )
        if self.verdict != derived_verdict:
            raise ValueError(
                "quality judgement verdict is inconsistent with deterministic rubric policy"
            )
        self.needs_human_review = derived_review

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in [*self.critical_reason_codes, *policy_codes]:
            value = str(raw or "").strip().lower().replace(" ", "_")[:96]
            if value and value not in seen:
                normalized.append(value)
                seen.add(value)
        self.critical_reason_codes = normalized
        return self

    @property
    def average_score(self) -> float:
        return round(sum(item.score for item in self.dimensions) / len(self.dimensions), 3)

    def score_for(self, name: AgentQualityDimensionName) -> int:
        return next(item.score for item in self.dimensions if item.name == name)


class AgentHumanReview(AgentQualityContractModel):
    case_id: str = Field(min_length=1, max_length=160)
    verdict: AgentQualityVerdict
    reviewer: str = Field(default="human", max_length=160)
    reason_codes: list[str] = Field(default_factory=list, max_length=12)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def normalize_review(self) -> "AgentHumanReview":
        self.reason_codes = [
            str(item or "").strip().lower().replace(" ", "_")[:96]
            for item in self.reason_codes
            if str(item or "").strip()
        ]
        return self


@dataclass(frozen=True, slots=True)
class AgentQualityResolvedResult:
    case_id: str
    judge_verdict: AgentQualityVerdict
    final_verdict: AgentQualityVerdict
    average_score: float
    human_reviewed: bool
    human_override: bool
    needs_human_review: bool
    critical_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentQualityBatchResult:
    total_cases: int
    passed_cases: int
    review_cases: int
    failed_cases: int
    pass_rate: float
    judge_pass_rate: float
    judge_review_rate: float
    judge_fail_rate: float
    human_reviewed_rate: float
    pending_human_review_rate: float
    human_override_rate: float
    human_agreement_rate: float
    average_score: float
    correctness_average: float
    groundedness_average: float
    relevance_average: float
    completeness_average: float
    clarity_average: float
    safety_average: float
    results: tuple[AgentQualityResolvedResult, ...]


def load_quality_samples(path: str | Path) -> tuple[AgentQualitySample, ...]:
    samples: list[AgentQualitySample] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        sample = AgentQualitySample.model_validate(payload)
        if sample.case_id in seen:
            raise ValueError(f"Duplicate qualitative case_id: {sample.case_id}")
        seen.add(sample.case_id)
        samples.append(sample)
    return tuple(samples)


def load_human_reviews(path: str | Path) -> dict[str, AgentHumanReview]:
    review_path = Path(path)
    if not review_path.exists():
        return {}
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Human review file must contain a JSON list.")
    reviews: dict[str, AgentHumanReview] = {}
    for raw in payload:
        review = AgentHumanReview.model_validate(raw)
        if review.case_id in reviews:
            raise ValueError(f"Duplicate human review case_id: {review.case_id}")
        reviews[review.case_id] = review
    return reviews


def resolve_quality_batch(
    judgements: tuple[AgentQualityJudgement, ...],
    *,
    human_reviews: dict[str, AgentHumanReview] | None = None,
) -> AgentQualityBatchResult:
    reviews = human_reviews or {}
    resolved: list[AgentQualityResolvedResult] = []
    dimensions: dict[str, list[int]] = {
        "correctness": [],
        "groundedness": [],
        "relevance": [],
        "completeness": [],
        "clarity": [],
        "safety": [],
    }
    for judgement in judgements:
        review = reviews.get(judgement.case_id)
        final_verdict = review.verdict if review is not None else judgement.verdict
        for item in judgement.dimensions:
            dimensions[item.name].append(item.score)
        resolved.append(
            AgentQualityResolvedResult(
                case_id=judgement.case_id,
                judge_verdict=judgement.verdict,
                final_verdict=final_verdict,
                average_score=judgement.average_score,
                human_reviewed=review is not None,
                human_override=review is not None and review.verdict != judgement.verdict,
                needs_human_review=judgement.needs_human_review and review is None,
                critical_reason_codes=tuple(judgement.critical_reason_codes),
            )
        )

    total = len(resolved)
    passed = sum(item.final_verdict == "pass" for item in resolved)
    review_count = sum(item.final_verdict == "review" for item in resolved)
    failed = sum(item.final_verdict == "fail" for item in resolved)
    judge_passed = sum(item.judge_verdict == "pass" for item in resolved)
    judge_review = sum(item.judge_verdict == "review" for item in resolved)
    judge_failed = sum(item.judge_verdict == "fail" for item in resolved)
    reviewed = sum(item.human_reviewed for item in resolved)
    overrides = sum(item.human_override for item in resolved)
    agreements = sum(
        item.human_reviewed and not item.human_override for item in resolved
    )
    pending_human = sum(item.needs_human_review for item in resolved)

    def rate(value: int, denominator: int = total) -> float:
        return round(value / denominator, 4) if denominator else 0.0

    def average(name: str) -> float:
        values = dimensions[name]
        return round(sum(values) / len(values), 3) if values else 0.0

    return AgentQualityBatchResult(
        total_cases=total,
        passed_cases=passed,
        review_cases=review_count,
        failed_cases=failed,
        pass_rate=rate(passed),
        judge_pass_rate=rate(judge_passed),
        judge_review_rate=rate(judge_review),
        judge_fail_rate=rate(judge_failed),
        human_reviewed_rate=rate(reviewed),
        pending_human_review_rate=rate(pending_human),
        human_override_rate=rate(overrides),
        human_agreement_rate=rate(agreements, reviewed),
        average_score=(
            round(sum(item.average_score for item in resolved) / total, 3)
            if total
            else 0.0
        ),
        correctness_average=average("correctness"),
        groundedness_average=average("groundedness"),
        relevance_average=average("relevance"),
        completeness_average=average("completeness"),
        clarity_average=average("clarity"),
        safety_average=average("safety"),
        results=tuple(resolved),
    )


__all__ = [
    "AgentHumanReview",
    "AgentQualityBatchResult",
    "AgentQualityDimension",
    "AgentQualityJudgement",
    "AgentQualityResolvedResult",
    "AgentQualitySample",
    "AgentQualityVerdict",
    "derive_quality_verdict",
    "load_human_reviews",
    "load_quality_samples",
    "resolve_quality_batch",
]
