from __future__ import annotations

from backend.rag.evidence_requirements import (
    assess_evidence_requirements,
    evidence_requirement_coverage,
    infer_evidence_requirements,
)
from backend.rag.models import DocumentChunk, RetrievalCandidate


def test_requirement_inference_and_coverage_track_missing_evidence_types() -> None:
    requirements = infer_evidence_requirements(
        "How does the method improve accuracy on the dataset?"
    )
    candidate = RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id="chunk-method",
            document_id="qasper:validation:paper-1",
            text="The proposed method uses a two-stage pipeline.",
            section_heading="Methods",
            chunk_index=0,
            token_count=8,
        )
    )

    assessed = assess_evidence_requirements(requirements, [candidate])

    by_type = {item.type: item for item in assessed}
    assert set(by_type) == {"method", "result", "data"}
    assert by_type["method"].status == "covered"
    assert by_type["method"].covered_chunk_ids == ("chunk-method",)
    assert by_type["result"].status == "missing"
    assert by_type["data"].status == "missing"
    assert evidence_requirement_coverage(assessed) == 1 / 3
    assert all(item.query.startswith("How does the method") for item in assessed)
