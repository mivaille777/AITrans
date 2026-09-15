from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from threading import RLock
from typing import Any

from backend.rag.config import RagRerankerConfig
from backend.rag.embeddings.runtime import resolve_embedding_device
from backend.rag.exceptions import RagRetrievalError
from backend.rag.model_manager import RERANKER_MODEL_ID, ModelManager
from backend.rag.models import RetrievalCandidate


def _factory(*args: Any, **kwargs: Any) -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(*args, **kwargs)


class Qwen3RerankerProvider:
    def __init__(
        self,
        config: RagRerankerConfig | None = None,
        *,
        model_factory: Callable[..., Any] | None = None,
        torch_module: Any | None = None,
        model_manager: ModelManager | None = None,
    ) -> None:
        self._config = config or RagRerankerConfig()
        self._factory = model_factory or _factory
        self._torch = torch_module
        self._model_manager = model_manager
        self._model: Any | None = None
        self._lock = RLock()
        if not self._config.lazy_load:
            self._ensure_model()

    def rerank(self, query, candidates, *, top_k):
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not candidates:
            return []
        model = self._ensure_model()
        pairs = [(query, self._candidate_text(candidate)) for candidate in candidates]
        scores = model.predict(
            pairs,
            batch_size=self._config.batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if not isinstance(scores, Sequence) or len(scores) != len(candidates):
            raise RagRetrievalError("reranker score count mismatch")
        scored = []
        for candidate, score in zip(candidates, scores, strict=True):
            value = float(score)
            if not math.isfinite(value):
                raise RagRetrievalError("reranker produced a non-finite score")
            scored.append(candidate.model_copy(update={"rerank_score": value}))
        ordered = sorted(
            scored,
            key=lambda item: (
                -float(item.rerank_score),
                item.rank or 10**9,
                item.chunk.chunk_id,
            ),
        )[:top_k]
        return [
            item.model_copy(update={"rank": rank})
            for rank, item in enumerate(ordered, 1)
        ]

    @staticmethod
    def _candidate_text(candidate: RetrievalCandidate) -> str:
        chunk = candidate.chunk
        parts: list[str] = []
        if chunk.title.strip():
            parts.append(f"Document: {chunk.title.strip()}")
        hierarchy = " > ".join(
            item.strip() for item in chunk.section_path if item.strip()
        )
        if hierarchy:
            parts.append(f"Hierarchy: {hierarchy}")
        elif chunk.section_heading.strip():
            parts.append(f"Section: {chunk.section_heading.strip()}")
        if chunk.chunk_type.strip():
            parts.append(f"Type: {chunk.chunk_type.strip()}")
        special_labels = chunk.metadata.get("special_labels", [])
        if isinstance(special_labels, list):
            labels = ", ".join(
                str(item).strip() for item in special_labels if str(item).strip()
            )
            if labels:
                parts.append(f"Labels: {labels}")
        if chunk.page_number is not None:
            parts.append(f"Page: {chunk.page_number}")
        parts.append(f"Content:\n{chunk.text}")
        return "\n".join(parts)

    def _ensure_model(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if self._torch is None:
                import torch

                self._torch = torch
            device = resolve_embedding_device(self._config.device, self._torch)
            configured_path = self._config.model_path.strip()
            if configured_path:
                source = configured_path
                local_files_only = self._config.local_files_only
            elif self._model_manager is not None:
                source = str(self._model_manager.get_model_path(RERANKER_MODEL_ID))
                local_files_only = True
            else:
                source = self._config.model
                local_files_only = self._config.local_files_only
            self._model = self._factory(
                source,
                device=device,
                local_files_only=local_files_only,
            )
            return self._model


__all__ = ["Qwen3RerankerProvider"]
