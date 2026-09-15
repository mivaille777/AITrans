from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.rag.models import (
    DocumentChunk,
    KnowledgeDocument,
    RetrievalCandidate,
    RetrievalContextWindow,
    RetrievalResult,
    build_stable_chunk_id,
)


def make_chunk(**overrides: object) -> DocumentChunk:
    values: dict[str, object] = {
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "text": "Gaussian processes can guide PID tuning.",
        "chunk_index": 0,
        "start_char": 0,
        "end_char": 40,
        "page_number": 2,
        "section_heading": "Methods",
        "metadata": {"source": "paper"},
    }
    values.update(overrides)
    return DocumentChunk.model_validate(values)


def test_knowledge_document_requires_non_empty_id() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDocument(document_id="")


def test_contract_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDocument(document_id="doc_001", unexpected=True)


def test_chunk_rejects_inverted_character_range() -> None:
    with pytest.raises(ValidationError):
        make_chunk(start_char=12, end_char=4)


def test_chunk_metadata_and_optional_location_serialize_to_json() -> None:
    chunk = make_chunk(page_number=None, section_heading="")

    payload = json.loads(chunk.model_dump_json())

    assert payload["page_number"] is None
    assert payload["metadata"] == {"source": "paper"}


def test_stable_chunk_id_is_deterministic_and_content_sensitive() -> None:
    first = build_stable_chunk_id(
        document_hash="doc_hash",
        section_heading="3.4 Safety Gate",
        chunk_index=2,
        text="same chunk text",
    )
    second = build_stable_chunk_id(
        document_hash="doc_hash",
        section_heading="3.4 Safety Gate",
        chunk_index=2,
        text="same chunk text",
    )
    changed = build_stable_chunk_id(
        document_hash="doc_hash",
        section_heading="3.4 Safety Gate",
        chunk_index=2,
        text="changed chunk text",
    )

    assert first == second
    assert first.startswith("chunk_")
    assert changed != first


def test_retrieval_result_round_trip_preserves_scores() -> None:
    result = RetrievalResult(
        query="How is PID tuning performed?",
        retrieval_strategy="hybrid",
        elapsed_ms=4.2,
        candidates=[
            RetrievalCandidate(
                chunk=make_chunk(),
                dense_score=0.81,
                sparse_score=7.3,
                fusion_score=0.04,
                rerank_score=0.92,
                rank=1,
            )
        ],
    )

    restored = RetrievalResult.model_validate_json(result.model_dump_json())

    assert restored.query == result.query
    assert restored.candidates[0].chunk.document_id == "doc_001"
    assert restored.candidates[0].rerank_score == pytest.approx(0.92)


def test_retrieval_result_round_trip_preserves_small_to_big_window() -> None:
    anchor = make_chunk(
        chunk_id="anchor",
        section_path=["3 Methodology", "3.2 GP"],
        chunk_index=1,
    )
    neighbor = make_chunk(
        chunk_id="neighbor",
        text="The following paragraph explains the mechanism.",
        section_path=["3 Methodology", "3.2 GP"],
        chunk_index=2,
        start_char=41,
        end_char=88,
    )
    result = RetrievalResult(
        query="What is the role of GP?",
        candidates=[
            RetrievalCandidate(
                chunk=anchor,
                rank=1,
                context_window=RetrievalContextWindow(
                    anchor_chunk_id="anchor",
                    chunks=[anchor, neighbor],
                    text=f"{anchor.text}\n\n{neighbor.text}",
                    token_count=16,
                    page_start=2,
                    page_end=2,
                ),
            )
        ],
    )

    restored = RetrievalResult.model_validate_json(result.model_dump_json())

    window = restored.candidates[0].context_window
    assert window is not None
    assert window.anchor_chunk_id == "anchor"
    assert [chunk.chunk_id for chunk in window.chunks] == ["anchor", "neighbor"]
    assert "following paragraph" in window.text
