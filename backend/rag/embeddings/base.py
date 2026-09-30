from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, runtime_checkable

QWEN3_QUERY_PREFIX = "query"
QWEN3_DOCUMENT_PREFIX = ""


@dataclass(frozen=True, slots=True)
class EmbeddingFingerprint:
    """Stable identity for the inputs that determine an embedding vector space."""

    model_id: str
    dimension: int
    normalized: bool
    query_prefix: str
    document_prefix: str
    schema_version: int = 1
    model_revision: str = ""

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("embedding fingerprint model_id must not be empty")
        if self.dimension < 1:
            raise ValueError("embedding fingerprint dimension must be positive")
        if self.schema_version < 1:
            raise ValueError("embedding fingerprint schema_version must be positive")

    def payload(self) -> dict[str, str | int | bool]:
        payload: dict[str, str | int | bool] = {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "dimension": self.dimension,
            "normalized": self.normalized,
            "query_prefix": self.query_prefix,
            "document_prefix": self.document_prefix,
        }
        if self.model_revision:
            payload["model_revision"] = self.model_revision
        return payload

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            self.payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, str | int | bool]:
        return {**self.payload(), "digest": self.digest}


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    @property
    def fingerprint(self) -> EmbeddingFingerprint: ...

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def embedding_fingerprint(provider: EmbeddingProvider) -> EmbeddingFingerprint:
    """Use the real provider identity, retaining compatibility with legacy adapters."""
    fingerprint = getattr(provider, "fingerprint", None)
    if fingerprint is not None:
        if not isinstance(fingerprint, EmbeddingFingerprint):
            raise TypeError("provider fingerprint must be an EmbeddingFingerprint")
        return fingerprint
    return EmbeddingFingerprint(
        model_id=provider.model_name,
        dimension=provider.dimension,
        normalized=True,
        query_prefix=QWEN3_QUERY_PREFIX,
        document_prefix=QWEN3_DOCUMENT_PREFIX,
    )


__all__ = [
    "QWEN3_DOCUMENT_PREFIX",
    "QWEN3_QUERY_PREFIX",
    "EmbeddingFingerprint",
    "EmbeddingProvider",
    "embedding_fingerprint",
]
