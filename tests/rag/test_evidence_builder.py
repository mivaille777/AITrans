from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult


def _result(
    *,
    page_number: int | None = 12,
    section_heading: str = "3.4",
    title: str = "Control Paper",
    source_uri: str = "file:///control.pdf",
    **scores: float | None,
) -> RetrievalResult:
    candidate = RetrievalCandidate(
        chunk=DocumentChunk(
            chunk_id="chunk-stable",
            document_id="doc-control",
            text="Gaussian processes guide PID tuning.",
            title=title,
            source_uri=source_uri,
            section_heading=section_heading,
            page_number=page_number,
            chunk_index=0,
            start_char=0,
            end_char=36,
        ),
        rank=1,
        **scores,
    )
    return RetrievalResult(
        query="PID tuning",
        candidates=[candidate],
        retrieval_strategy="hybrid",
        elapsed_ms=2.5,
    )


@pytest.mark.parametrize(
    ("page_number", "section_heading", "expected"),
    [
        (12, "3.4", "Page 12 · Section 3.4"),
        (12, "", "Page 12"),
        (None, "3.4", "Section 3.4"),
    ],
)
def test_evidence_location_comes_from_chunk_provenance(
    page_number: int | None,
    section_heading: str,
    expected: str,
) -> None:
    evidence = build_agent_evidence(
        _result(page_number=page_number, section_heading=section_heading)
    )

    assert evidence[0].location == expected
    assert evidence[0].metadata["page_number"] == page_number
    assert evidence[0].metadata["section_heading"] == section_heading


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        (
            {
                "rerank_score": 0.91,
                "fusion_score": 0.31,
                "dense_score": 0.81,
                "sparse_score": 7.0,
            },
            0.91,
        ),
        ({"fusion_score": 0.31, "dense_score": 0.81, "sparse_score": 7.0}, 0.31),
        ({"dense_score": 0.81, "sparse_score": 7.0}, 0.81),
        ({"sparse_score": 7.0}, 7.0),
    ],
)
def test_evidence_score_uses_retrieval_precedence(
    scores: dict[str, float],
    expected: float,
) -> None:
    evidence = build_agent_evidence(_result(**scores))

    assert evidence[0].score == pytest.approx(expected)


def test_evidence_preserves_empty_title_and_source() -> None:
    evidence = build_agent_evidence(_result(title="", source_uri=""))[0]

    assert evidence.title == ""
    assert evidence.resource_url == ""
    assert evidence.source_type == "knowledge"
    assert evidence.source_id == "doc-control"
    assert evidence.excerpt == "Gaussian processes guide PID tuning."


def test_evidence_id_is_stable_for_the_same_chunk() -> None:
    first = build_agent_evidence(_result())[0]
    second = build_agent_evidence(_result())[0]

    assert first.evidence_id == second.evidence_id == "evidence:chunk-stable"


def test_evidence_metadata_is_json_safe() -> None:
    result = _result(dense_score=0.8)
    result.metadata.update(
        {
            "indexed_at": datetime(2026, 8, 24, tzinfo=UTC),
            "path": Path("documents/control.pdf"),
            "labels": {"control", "pid"},
            "non_finite": float("nan"),
        }
    )
    result.candidates[0].metadata["tuple"] = ("dense", 1)

    evidence = build_agent_evidence(result)[0]
    encoded = json.dumps(evidence.metadata, allow_nan=False)

    assert '"indexed_at": "2026-08-24T00:00:00+00:00"' in encoded
    assert evidence.metadata["retrieval"]["path"] == str(Path("documents/control.pdf"))
    assert evidence.metadata["retrieval"]["labels"] == ["control", "pid"]
    assert evidence.metadata["retrieval"]["non_finite"] is None
    assert evidence.metadata["candidate"]["tuple"] == ["dense", 1]
