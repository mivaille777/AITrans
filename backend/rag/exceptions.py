from __future__ import annotations


class RagError(RuntimeError):
    """Base exception for RAG-domain failures."""


class RagConfigurationError(RagError):
    """Raised when runtime RAG configuration cannot be used."""


class RagInvariantError(RagError):
    """Raised when a RAG-domain invariant is violated at runtime."""


class RagParsingError(RagError):
    """Raised when a source document cannot be normalized safely."""


class RagEmbeddingError(RagError):
    """Raised when an embedding runtime cannot load or produce valid vectors."""


class RagVectorStoreError(RagError):
    """Raised when the local vector store cannot complete an operation."""


class RagRetrievalError(RagError):
    """Raised when no configured retrieval path can serve a query."""


class RagModelManagerError(RagError):
    """Raised when a managed local model operation cannot complete safely."""


class UnsupportedDocumentTypeError(RagParsingError):
    """Raised when no basic ingestion parser supports a document type."""


__all__ = [
    "RagConfigurationError",
    "RagEmbeddingError",
    "RagError",
    "RagInvariantError",
    "RagModelManagerError",
    "RagParsingError",
    "RagRetrievalError",
    "RagVectorStoreError",
    "UnsupportedDocumentTypeError",
]
