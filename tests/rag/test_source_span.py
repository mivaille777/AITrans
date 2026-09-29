from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.rag.models import DocumentChunk
from backend.rag.source_span import SourceSpan, SourceSpanError, resolve_source_span


def test_source_span_round_trips_exact_unicode_source_range() -> None:
    source_text = "标题\nEvidence — café 🧪 supports the result.\n"
    selected_text = "Evidence — café 🧪"
    start_char = source_text.index(selected_text)
    end_char = start_char + len(selected_text)
    document_hash = sha256(b"original source bytes").hexdigest()

    span = SourceSpan.from_text(
        source_text,
        start_char=start_char,
        end_char=end_char,
        document_hash=document_hash,
        source_uri="file:///paper.txt",
        page_start=1,
        page_end=1,
    )
    restored = SourceSpan.model_validate_json(span.model_dump_json())

    assert restored.version == 1
    assert restored.coordinate_space == "normalized_document_text"
    assert (
        resolve_source_span(
            restored,
            source_text,
            expected_document_hash=document_hash,
        )
        == selected_text
    )


def test_chunk_json_keeps_source_span_and_rejects_range_mismatch() -> None:
    source_text = "prefix evidence suffix"
    selected_text = "evidence"
    start_char = source_text.index(selected_text)
    end_char = start_char + len(selected_text)
    document_hash = sha256(b"paper").hexdigest()
    span = SourceSpan.from_text(
        source_text,
        start_char=start_char,
        end_char=end_char,
        document_hash=document_hash,
        source_uri="file:///paper.txt",
    )
    chunk = DocumentChunk(
        chunk_id="chunk_evidence",
        document_id="doc_paper",
        text=selected_text,
        chunk_index=0,
        start_char=start_char,
        end_char=end_char,
        source_uri="file:///paper.txt",
        document_hash=document_hash,
        source_span=span,
    )

    restored = DocumentChunk.model_validate_json(chunk.model_dump_json())

    assert restored.source_span == span
    assert resolve_source_span(restored.source_span, source_text) == selected_text
    with pytest.raises(ValidationError, match="must match its source_span"):
        DocumentChunk.model_validate(
            {
                **chunk.model_dump(mode="json"),
                "start_char": start_char + 1,
            }
        )


def test_old_chunk_json_without_source_span_remains_compatible() -> None:
    payload = {
        "chunk_id": "legacy_chunk",
        "document_id": "legacy_doc",
        "text": "Legacy indexed evidence.",
        "chunk_index": 0,
        "start_char": 0,
        "end_char": 24,
    }

    chunk = DocumentChunk.model_validate(payload)

    assert chunk.source_span is None
    assert "source_span" not in payload


@pytest.mark.parametrize(
    ("source_text", "expected_document_hash", "message"),
    [
        ("changed normalized text", "doc-hash", "text does not match"),
        ("prefix evidence suffix", "new-doc-hash", "different document version"),
    ],
)
def test_source_span_refuses_stale_source_versions(
    source_text: str,
    expected_document_hash: str,
    message: str,
) -> None:
    original_text = "prefix evidence suffix"
    document_hash = "doc-hash"
    span = SourceSpan.from_text(
        original_text,
        start_char=7,
        end_char=15,
        document_hash=document_hash,
    )

    with pytest.raises(SourceSpanError, match=message):
        resolve_source_span(
            span,
            source_text,
            expected_document_hash=expected_document_hash,
        )


def test_source_span_rejects_invalid_ranges_and_incomplete_page_ranges() -> None:
    source_text = "evidence"
    with pytest.raises(SourceSpanError, match="outside normalized text"):
        SourceSpan.from_text(
            source_text,
            start_char=0,
            end_char=99,
            document_hash="doc-hash",
        )

    with pytest.raises(ValidationError, match="must both be set"):
        SourceSpan(
            document_hash="doc-hash",
            document_text_hash=sha256(source_text.encode()).hexdigest(),
            start_char=0,
            end_char=1,
            quote_hash=sha256(b"e").hexdigest(),
            page_start=1,
        )
