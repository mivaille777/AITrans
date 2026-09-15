from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings.base import EmbeddingProvider
from backend.rag.exceptions import RagConfigurationError
from backend.rag.model_manager import ModelManager


class EmbeddingRuntimeStatus(str, Enum):
    UNINITIALIZED = "uninitialized"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeSnapshot:
    status: EmbeddingRuntimeStatus
    model_name: str
    device: str
    dimension: int
    load_time_ms: float = 0.0
    last_error: str = ""
    allocated_vram_mb: float | None = None
    reserved_vram_mb: float | None = None


def resolve_embedding_device(configured_device: str, torch_module: Any) -> str:
    if configured_device == "cpu":
        return "cpu"
    cuda_available = bool(torch_module.cuda.is_available())
    if configured_device == "cuda":
        if not cuda_available:
            raise RagConfigurationError(
                "RAG embedding device is 'cuda' but CUDA is not available"
            )
        return "cuda"
    if configured_device == "auto":
        return "cuda" if cuda_available else "cpu"
    raise RagConfigurationError(
        f"unsupported RAG embedding device: {configured_device!r}"
    )


def create_embedding_provider(
    config: RagEmbeddingConfig,
    *,
    model_manager: ModelManager | None = None,
) -> EmbeddingProvider:
    if config.provider != "qwen3":
        raise RagConfigurationError(
            f"unsupported RAG embedding provider: {config.provider!r}"
        )
    from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider

    return Qwen3EmbeddingProvider(config, model_manager=model_manager)


__all__ = [
    "EmbeddingRuntimeSnapshot",
    "EmbeddingRuntimeStatus",
    "create_embedding_provider",
    "resolve_embedding_device",
]
