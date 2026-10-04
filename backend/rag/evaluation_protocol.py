from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from backend.rag.models import RagContractModel


class ClaimAssessment(RagContractModel):
    case_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    supported: bool
    citation_correct: bool
    assessor: str = Field(min_length=1)
    method: Literal["human", "calibrated_judge"]
    review_id: str = Field(min_length=1)
    calibration_id: str = ""


def assessment_map(assessments: Sequence[ClaimAssessment]) -> dict[tuple[str, str], ClaimAssessment]:
    result = {}
    for item in assessments:
        key = (item.case_id, item.claim_id)
        if key in result:
            raise ValueError(f"duplicate independent assessment: {key}")
        if item.method == "calibrated_judge" and not item.calibration_id:
            raise ValueError("judge assessment requires an independent calibration record")
        result[key] = item
    return result


def compare_assessments(human: Sequence[ClaimAssessment], judge: Sequence[ClaimAssessment]) -> dict:
    left, right = assessment_map(human), assessment_map(judge)
    common = left.keys() & right.keys()
    disputes = sorted(key for key in common if (
        left[key].supported, left[key].citation_correct
    ) != (right[key].supported, right[key].citation_correct))
    return {"samples": len(common), "agreement": (1 - len(disputes)/len(common)) if common else None,
            "disputes": disputes}
