from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

_METRIC_FIELDS = {
    "Answer F1": "official_answer_f1",
    "Evidence F1": "official_evidence_f1",
    "Recall@10": "gold_evidence_recall_at_10",
    "MRR": "MRR",
}


def _indexed_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        question_id = str(case.get("question_id", "")).strip()
        if not question_id:
            raise ValueError("every per-question metric row must have a question_id")
        if question_id in indexed:
            raise ValueError(f"duplicate per-question metric row: {question_id}")
        indexed[question_id] = case
    return indexed


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def paired_bootstrap(
    baseline_cases: Sequence[Mapping[str, Any]],
    candidate_cases: Sequence[Mapping[str, Any]],
    *,
    seed: int = 42,
    resamples: int = 5000,
) -> dict[str, Any]:
    """Estimate candidate-minus-baseline deltas and paired percentile CIs."""

    if resamples < 100 or resamples > 50_000:
        raise ValueError("resamples must be between 100 and 50000")
    baseline = _indexed_cases(baseline_cases)
    candidate = _indexed_cases(candidate_cases)
    question_ids = sorted(set(baseline).intersection(candidate))
    if not question_ids:
        raise ValueError("runs do not contain any paired questions")

    rng = random.Random(seed)
    result: dict[str, Any] = {
        "paired_question_count": len(question_ids),
        "question_ids": question_ids,
        "seed": seed,
        "resamples": resamples,
        "confidence_level": 0.95,
        "metrics": {},
    }
    for metric_index, (metric_name, field) in enumerate(_METRIC_FIELDS.items()):
        pairs: list[tuple[float, float]] = []
        for question_id in question_ids:
            left = baseline[question_id].get(field)
            right = candidate[question_id].get(field)
            if isinstance(left, bool) or isinstance(right, bool):
                continue
            if not isinstance(left, (int, float)) or not isinstance(
                right, (int, float)
            ):
                continue
            if not isfinite(float(left)) or not isfinite(float(right)):
                continue
            pairs.append((float(left), float(right)))
        if not pairs:
            result["metrics"][metric_name] = {
                "paired_count": 0,
                "baseline_mean": None,
                "candidate_mean": None,
                "delta": None,
                "ci_95": None,
            }
            continue

        baseline_mean = sum(left for left, _ in pairs) / len(pairs)
        candidate_mean = sum(right for _, right in pairs) / len(pairs)
        deltas = [right - left for left, right in pairs]
        bootstrap_deltas = [
            sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas)
            for _ in range(resamples)
        ]
        result["metrics"][metric_name] = {
            "paired_count": len(pairs),
            "baseline_mean": baseline_mean,
            "candidate_mean": candidate_mean,
            "delta": candidate_mean - baseline_mean,
            "ci_95": {
                "lower": _quantile(bootstrap_deltas, 0.025),
                "upper": _quantile(bootstrap_deltas, 0.975),
            },
        }
        rng.seed(seed + metric_index + 1)
    return result


__all__ = ["paired_bootstrap"]
