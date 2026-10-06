"""Model-independent late-interaction scoring, with bounded temporary memory."""

from __future__ import annotations

import numpy as np

from backend.rag.exceptions import RagVectorStoreError
from backend.rag.stores.local_repository import normalize_rows, vector_array


def validate_multivector(vector, dimension: int) -> list[list[float]]:
    return vector_array(vector, dimension, multivector=True).tolist()


def pool_multivector(vector, dimension: int) -> list[float]:
    rows = vector_array(vector, dimension, multivector=True)
    pooled = rows.astype(np.float64).mean(axis=0)
    norm = np.linalg.norm(pooled)
    if norm <= 1e-12:
        raise RagVectorStoreError(
            "cannot build a coarse visual vector from a zero-energy multivector"
        )
    return (pooled / norm).astype(np.float32).tolist()


def maxsim(query, page, *, distance: str = "dot", block_size: int = 256) -> float:
    if block_size <= 0:
        raise RagVectorStoreError("MaxSim block size must be positive")
    try:
        dimension = np.asarray(query).shape[-1]
    except (IndexError, ValueError) as exc:
        raise RagVectorStoreError("invalid query multivector") from exc
    q = vector_array(query, dimension, multivector=True)
    p = vector_array(page, dimension, multivector=True)
    if distance == "cosine":
        q, p = normalize_rows(q), normalize_rows(p)
    elif distance != "dot":
        raise RagVectorStoreError("visual distance must be dot or cosine")
    # Callers pass actual token matrices, never padded batches. Initializing to
    # -inf prevents zero from winning when every real token similarity is negative.
    maxima = np.full(len(q), -np.inf, dtype=np.float32)
    for start in range(0, len(p), block_size):
        maxima = np.maximum(maxima, (q @ p[start : start + block_size].T).max(axis=1))
    score = float(maxima.sum(dtype=np.float32))
    if not np.isfinite(score):
        raise RagVectorStoreError("non-finite MaxSim score")
    return score
