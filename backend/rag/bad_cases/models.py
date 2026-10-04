from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from backend.rag.evaluation_dataset import RagEvaluationCase
from backend.rag.models import RagContractModel

FAILURE_STAGES = (
    "PARSER", "CHUNK", "EMBEDDING", "VECTOR", "BM25", "ENTITY_EXTRACTION",
    "ENTITY_RESOLUTION", "GRAPH_BUILD", "GRAPH_TRAVERSAL", "REWRITE", "ROUTER",
    "RERANK", "CONTEXT", "CITATION", "GENERATION", "SCOPE_ERROR",
    "INDEX_CONSISTENCY_ERROR", "EVALUATION_LABEL_ERROR",
)


class RagBadCase(RagContractModel):
    schema_version: Literal[1] = 1
    source_redacted: bool = False
    case: RagEvaluationCase
    trace_id: str = Field(min_length=1)
    generations: dict[str, str | None]
    fingerprints: dict[str, str]
    stages: dict[str, list[str]] = Field(default_factory=dict)
    answer: str = ""
    citations: list[dict] = Field(default_factory=list)
    graph_paths: list[dict] = Field(default_factory=list)
    first_failed_stage: str = ""
    root_cause: str = ""
    status: Literal["open", "fixed", "deferred"] = "open"
    repair_commit: str = ""
    regression_test: str = ""

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.first_failed_stage and self.first_failed_stage not in FAILURE_STAGES:
            raise ValueError("unknown first_failed_stage")
        if self.status == "fixed" and not (self.repair_commit and self.regression_test and self.root_cause):
            raise ValueError("fixed bad case requires root cause, repair commit and regression test")
        return self
