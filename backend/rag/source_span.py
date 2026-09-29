from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCE_SPAN_VERSION = 1
SOURCE_SPAN_COORDINATE_SPACE = "normalized_document_text"


class SourceSpanError(ValueError):
    """Raised when a source span cannot be verified against source text."""


class SourceSpan(BaseModel):
    """Versioned half-open range into parser-normalized document text.

    Character offsets use Python Unicode code points over the exact normalized
    text returned by the parser. ``document_hash`` fingerprints the raw source
    document; ``document_text_hash`` fingerprints the normalized text used by
    these offsets. The selected quote hash detects stale or misaligned ranges.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = SOURCE_SPAN_VERSION
    coordinate_space: Literal["normalized_document_text"] = SOURCE_SPAN_COORDINATE_SPACE
    document_hash: str = Field(min_length=1)
    document_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    quote_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_uri: str = ""
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> SourceSpan:
        if self.end_char <= self.start_char:
            raise ValueError("source span end_char must be greater than start_char")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError(
                "page_start and page_end must both be set or both be empty"
            )
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be greater than or equal to page_start")
        return self

    @classmethod
    def from_text(
        cls,
        source_text: str,
        *,
        start_char: int,
        end_char: int,
        document_hash: str,
        source_uri: str = "",
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> SourceSpan:
        """Create a checked span and hashes from normalized source text."""

        if end_char <= start_char:
            raise SourceSpanError("source span must contain at least one character")
        if start_char < 0 or end_char > len(source_text):
            raise SourceSpanError(
                f"source span is outside normalized text: [{start_char}, {end_char})"
            )
        selected_text = source_text[start_char:end_char]
        if not selected_text:
            raise SourceSpanError("source span resolves to empty text")
        return cls(
            document_hash=document_hash,
            document_text_hash=_text_hash(source_text),
            start_char=start_char,
            end_char=end_char,
            quote_hash=_text_hash(selected_text),
            source_uri=source_uri,
            page_start=page_start,
            page_end=page_end,
        )


def resolve_source_span(
    span: SourceSpan,
    source_text: str,
    *,
    expected_document_hash: str | None = None,
) -> str:
    """Resolve a span only when both source and normalized-text versions match."""

    if (
        expected_document_hash is not None
        and span.document_hash != expected_document_hash
    ):
        raise SourceSpanError("source span refers to a different document version")
    if _text_hash(source_text) != span.document_text_hash:
        raise SourceSpanError(
            "normalized source text does not match source span version"
        )
    if span.end_char > len(source_text):
        raise SourceSpanError("source span end offset is outside normalized text")
    selected_text = source_text[span.start_char : span.end_char]
    if not selected_text or _text_hash(selected_text) != span.quote_hash:
        raise SourceSpanError("source span quote hash does not match selected text")
    return selected_text


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "SOURCE_SPAN_COORDINATE_SPACE",
    "SOURCE_SPAN_VERSION",
    "SourceSpan",
    "SourceSpanError",
    "resolve_source_span",
]
