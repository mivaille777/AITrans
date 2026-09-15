from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from threading import RLock
from time import perf_counter
from typing import Any

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings.runtime import (
    EmbeddingRuntimeSnapshot,
    EmbeddingRuntimeStatus,
    resolve_embedding_device,
)
from backend.rag.exceptions import (
    RagConfigurationError,
    RagEmbeddingError,
    RagModelManagerError,
)
from backend.rag.model_manager import EMBEDDING_MODEL_ID, ModelManager

ModelFactory = Callable[..., Any]


def _default_model_factory(*args: Any, **kwargs: Any) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RagEmbeddingError(
            "sentence-transformers is required for the Qwen3 embedding provider"
        ) from exc
    return SentenceTransformer(*args, **kwargs)


def _load_torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise RagEmbeddingError("PyTorch is required for Qwen3 embeddings") from exc
    return torch


class Qwen3EmbeddingProvider:
    """Lazy, reusable Sentence Transformers runtime for Qwen3 embeddings."""

    def __init__(
        self,
        config: RagEmbeddingConfig | None = None,
        *,
        model_factory: ModelFactory | None = None,
        torch_module: Any | None = None,
        model_manager: ModelManager | None = None,
    ) -> None:
        self._config = config or RagEmbeddingConfig()
        if not self._config.normalize:
            raise RagConfigurationError(
                "Qwen3 embedding vectors must use normalize_embeddings=True"
            )
        self._model_factory = model_factory or _default_model_factory
        self._torch = torch_module
        self._model_manager = model_manager
        self._model: Any | None = None
        self._lock = RLock()
        self._status = EmbeddingRuntimeStatus.UNINITIALIZED
        self._device = self._config.device
        self._load_time_ms = 0.0
        self._last_error = ""
        self._allocated_vram_mb: float | None = None
        self._reserved_vram_mb: float | None = None
        self._retry_when_managed_model_installed = False

    @property
    def dimension(self) -> int:
        return self._config.dimension

    @property
    def model_name(self) -> str:
        return self._config.model

    @property
    def runtime(self) -> EmbeddingRuntimeSnapshot:
        with self._lock:
            return EmbeddingRuntimeSnapshot(
                status=self._status,
                model_name=self.model_name,
                device=self._device,
                dimension=self.dimension,
                load_time_ms=self._load_time_ms,
                last_error=self._last_error,
                allocated_vram_mb=self._allocated_vram_mb,
                reserved_vram_mb=self._reserved_vram_mb,
            )

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise RagEmbeddingError("embedding query must not be empty")
        model = self._ensure_model()
        vectors = self._encode_query(model, text)
        return self._validate_vectors(vectors, expected_count=1)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text or not text.strip() for text in texts):
            raise RagEmbeddingError("embedding documents must not contain empty text")
        model = self._ensure_model()
        vectors = model.encode(
            texts,
            batch_size=self._config.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            truncate_dim=self.dimension,
        )
        return self._validate_vectors(vectors, expected_count=len(texts))

    def _managed_model_became_available(self) -> bool:
        if (
            not self._retry_when_managed_model_installed
            or self._model_manager is None
        ):
            return False
        try:
            return bool(self._model_manager.is_installed(EMBEDDING_MODEL_ID))
        except Exception:  # noqa: BLE001 - status probing must not mask the original load failure
            return False

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._status is EmbeddingRuntimeStatus.READY and self._model is not None:
                return self._model
            if self._status is EmbeddingRuntimeStatus.FAILED:
                if not self._managed_model_became_available():
                    raise RagEmbeddingError(
                        self._last_error or "Qwen3 embedding runtime previously failed"
                    )
                self._status = EmbeddingRuntimeStatus.UNINITIALIZED
                self._last_error = ""
                self._retry_when_managed_model_installed = False

            self._status = EmbeddingRuntimeStatus.LOADING
            started = perf_counter()
            try:
                torch_module = self._torch or _load_torch()
                self._torch = torch_module
                self._device = resolve_embedding_device(
                    self._config.device,
                    torch_module,
                )
                configured_path = self._config.model_path.strip()
                if configured_path:
                    model_source = configured_path
                    local_files_only = self._config.local_files_only
                elif self._model_manager is not None:
                    model_source = str(
                        self._model_manager.get_model_path(EMBEDDING_MODEL_ID)
                    )
                    local_files_only = True
                else:
                    model_source = self._config.model
                    local_files_only = self._config.local_files_only
                model_kwargs: dict[str, Any] = {}
                if self._config.precision != "default":
                    attribute = (
                        "float16" if self._config.precision == "fp16" else "bfloat16"
                    )
                    dtype = getattr(torch_module, attribute, None)
                    if dtype is None:
                        raise RagConfigurationError(
                            "PyTorch does not support requested precision: "
                            f"{self._config.precision}"
                        )
                    model_kwargs["torch_dtype"] = dtype
                model = self._model_factory(
                    model_source,
                    device=self._device,
                    local_files_only=local_files_only,
                    **({"model_kwargs": model_kwargs} if model_kwargs else {}),
                )
                self._apply_input_limit(model)
                if self._config.warmup:
                    warmup_vectors = self._encode_query(model, "warmup")
                    self._validate_vectors(warmup_vectors, expected_count=1)
                self._model = model
                self._load_time_ms = (perf_counter() - started) * 1000
                self._capture_gpu_memory()
                self._last_error = ""
                self._retry_when_managed_model_installed = False
                self._status = EmbeddingRuntimeStatus.READY
                return model
            except Exception as exc:
                self._model = None
                self._load_time_ms = (perf_counter() - started) * 1000
                self._last_error = str(exc) or exc.__class__.__name__
                self._retry_when_managed_model_installed = isinstance(
                    exc, RagModelManagerError
                )
                self._status = EmbeddingRuntimeStatus.FAILED
                if isinstance(exc, (RagConfigurationError, RagEmbeddingError)):
                    raise
                raise RagEmbeddingError(
                    f"failed to initialize Qwen3 embedding runtime: {self._last_error}"
                ) from exc

    def _apply_input_limit(self, model: Any) -> None:
        configured_limit = self._config.max_input_tokens
        current_limit = getattr(model, "max_seq_length", None)
        try:
            parsed_current = int(current_limit) if current_limit is not None else 0
        except (TypeError, ValueError):
            parsed_current = 0
        effective_limit = (
            min(parsed_current, configured_limit)
            if parsed_current > 0
            else configured_limit
        )
        try:
            model.max_seq_length = effective_limit
        except Exception as exc:
            raise RagConfigurationError(
                "Unable to apply max_input_tokens to Qwen3 embedding runtime"
            ) from exc

    def _encode_query(self, model: Any, text: str) -> Any:
        return model.encode(
            [text],
            prompt_name="query",
            batch_size=self._config.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            truncate_dim=self.dimension,
        )

    def _validate_vectors(
        self,
        values: Any,
        *,
        expected_count: int,
    ) -> list[list[float]]:
        if hasattr(values, "tolist"):
            values = values.tolist()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise RagEmbeddingError("embedding output must be a sequence of vectors")
        if len(values) != expected_count:
            raise RagEmbeddingError(
                f"embedding output count mismatch: expected {expected_count}, got {len(values)}"
            )

        validated: list[list[float]] = []
        for vector in values:
            if hasattr(vector, "tolist"):
                vector = vector.tolist()
            if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
                raise RagEmbeddingError("embedding vector must be a numeric sequence")
            if len(vector) != self.dimension:
                raise RagEmbeddingError(
                    f"embedding dimension mismatch: expected {self.dimension}, got {len(vector)}"
                )
            try:
                converted = [float(value) for value in vector]
            except (TypeError, ValueError) as exc:
                raise RagEmbeddingError(
                    "embedding vector contains a non-numeric value"
                ) from exc
            if not all(math.isfinite(value) for value in converted):
                raise RagEmbeddingError("embedding vector contains non-finite values")
            validated.append(converted)
        return validated

    def _capture_gpu_memory(self) -> None:
        if self._device != "cuda" or self._torch is None:
            return
        cuda = self._torch.cuda
        try:
            self._allocated_vram_mb = float(cuda.memory_allocated()) / (1024**2)
            self._reserved_vram_mb = float(cuda.memory_reserved()) / (1024**2)
        except (AttributeError, RuntimeError):
            self._allocated_vram_mb = None
            self._reserved_vram_mb = None


__all__ = ["Qwen3EmbeddingProvider"]
