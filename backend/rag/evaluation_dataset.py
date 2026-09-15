from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from backend.rag.models import RagContractModel

RagEvaluationCategory = Literal[
    "term",
    "exact_identifier",
    "cross_section",
    "multilingual",
    "multi_document",
    "no_answer",
]


class RagEvaluationClaim(RagContractModel):
    claim_id: str = Field(min_length=1)
    relevant_chunk_ids: list[str] = Field(default_factory=list)


class RagEvaluationCase(RagContractModel):
    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    categories: list[RagEvaluationCategory] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    relevance_grades: dict[str, int] = Field(default_factory=dict)
    claims: list[RagEvaluationClaim] = Field(default_factory=list)
    no_answer: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_annotations(self) -> RagEvaluationCase:
        if len(self.relevant_chunk_ids) != len(set(self.relevant_chunk_ids)):
            raise ValueError("relevant_chunk_ids must not contain duplicates")
        if any(grade < 0 for grade in self.relevance_grades.values()):
            raise ValueError("relevance grades must be non-negative")
        if self.no_answer and (self.relevant_chunk_ids or self.relevance_grades):
            raise ValueError("no-answer cases cannot declare relevant chunks")
        if self.no_answer and "no_answer" not in self.categories:
            raise ValueError("no-answer cases must include the no_answer category")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim_id values must be unique within a case")
        return self

    @property
    def graded_relevance(self) -> dict[str, int]:
        grades = {chunk_id: 1 for chunk_id in self.relevant_chunk_ids}
        grades.update(self.relevance_grades)
        return grades


class RagClaimPrediction(RagContractModel):
    claim_id: str = Field(min_length=1)
    cited_chunk_ids: list[str] = Field(default_factory=list)
    supported: bool | None = None


class RagEvaluationLatency(RagContractModel):
    query_embedding_ms: float = Field(default=0.0, ge=0.0)
    dense_search_ms: float = Field(default=0.0, ge=0.0)
    bm25_ms: float = Field(default=0.0, ge=0.0)
    rerank_ms: float = Field(default=0.0, ge=0.0)
    total_rag_ms: float = Field(default=0.0, ge=0.0)


class RagEvaluationPrediction(RagContractModel):
    case_id: str = Field(min_length=1)
    ranked_chunk_ids: list[str] = Field(default_factory=list)
    pre_rerank_chunk_ids: list[str] = Field(default_factory=list)
    claims: list[RagClaimPrediction] = Field(default_factory=list)
    latency: RagEvaluationLatency = Field(default_factory=RagEvaluationLatency)

    @model_validator(mode="after")
    def validate_prediction(self) -> RagEvaluationPrediction:
        if len(self.ranked_chunk_ids) != len(set(self.ranked_chunk_ids)):
            raise ValueError("ranked_chunk_ids must not contain duplicates")
        if len(self.pre_rerank_chunk_ids) != len(set(self.pre_rerank_chunk_ids)):
            raise ValueError("pre_rerank_chunk_ids must not contain duplicates")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("predicted claim_id values must be unique within a case")
        return self


def _load_json_records(path: str | Path) -> list[object]:
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    if source.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise TypeError(f"{source} must contain a JSON array or use JSONL")
    return payload


def load_evaluation_dataset(path: str | Path) -> list[RagEvaluationCase]:
    cases = [
        RagEvaluationCase.model_validate(item) for item in _load_json_records(path)
    ]
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case_id values must be unique")
    return cases


def load_evaluation_predictions(path: str | Path) -> list[RagEvaluationPrediction]:
    predictions = [
        RagEvaluationPrediction.model_validate(item)
        for item in _load_json_records(path)
    ]
    case_ids = [prediction.case_id for prediction in predictions]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("prediction case_id values must be unique")
    return predictions


__all__ = [
    "RagClaimPrediction",
    "RagEvaluationCase",
    "RagEvaluationCategory",
    "RagEvaluationClaim",
    "RagEvaluationLatency",
    "RagEvaluationPrediction",
    "load_evaluation_dataset",
    "load_evaluation_predictions",
]
