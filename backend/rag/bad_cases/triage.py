from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.rag.bad_cases.models import FAILURE_STAGES


def first_failed_stage(stages: Mapping[str, Sequence[str]], evidence_sets: Sequence[Sequence[str]]) -> str | None:
    """Only inspect recorded stages in execution order; absent stages are unknown."""
    if not evidence_sets or any(not group for group in evidence_sets):
        raise ValueError("triage requires nonempty independent evidence alternatives")
    for stage, ids in stages.items():
        if stage not in FAILURE_STAGES:
            raise ValueError(f"unknown failure stage: {stage}")
        if not any(set(group).issubset(ids) for group in evidence_sets):
            return stage
    return None
