from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings import EmbeddingProvider, Qwen3EmbeddingProvider
from backend.rag.embeddings.runtime import create_embedding_provider
from backend.rag.exceptions import (
    RagConfigurationError,
    RagEmbeddingError,
    RagModelManagerError,
)
from backend.rag.model_manager import EMBEDDING_MODEL_ID


class MinimalModel:
    def __init__(self) -> None:
        self.max_seq_length = 32_768

    def encode(self, texts: list[str], **_kwargs: object) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]


class CpuTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False


class DeferredModelManager:
    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.installed = False

    def is_installed(self, model_id: str) -> bool:
        assert model_id == EMBEDDING_MODEL_ID
        return self.installed

    def get_model_path(self, model_id: str) -> Path:
        assert model_id == EMBEDDING_MODEL_ID
        if not self.installed:
            raise RagModelManagerError("managed embedding model is not installed")
        return self.model_path


def test_qwen3_provider_satisfies_embedding_protocol() -> None:
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(dimension=2, warmup=False),
        model_factory=lambda *_args, **_kwargs: MinimalModel(),
        torch_module=CpuTorch(),
    )

    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimension == 2
    assert provider.model_name == "Qwen/Qwen3-Embedding-0.6B"


def test_embedding_device_configuration_is_validated() -> None:
    with pytest.raises(ValidationError, match="device"):
        RagEmbeddingConfig(device="metal")

    assert RagEmbeddingConfig(device=" CUDA ").device == "cuda"


def test_runtime_factory_rejects_unknown_provider() -> None:
    with pytest.raises(RagConfigurationError, match="unsupported"):
        create_embedding_provider(RagEmbeddingConfig(provider="other"))


def test_qwen3_provider_requires_normalized_vectors() -> None:
    with pytest.raises(RagConfigurationError, match="normalize_embeddings"):
        Qwen3EmbeddingProvider(RagEmbeddingConfig(normalize=False))


def test_qwen3_provider_applies_configured_input_token_limit() -> None:
    model = MinimalModel()
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(
            dimension=2,
            warmup=False,
            max_input_tokens=128,
        ),
        model_factory=lambda *_args, **_kwargs: model,
        torch_module=CpuTorch(),
    )

    assert provider.embed_query("query") == [0.0, 1.0]
    assert model.max_seq_length == 128


def test_missing_managed_embedding_can_recover_after_model_install(tmp_path: Path) -> None:
    manager = DeferredModelManager(tmp_path / "qwen3-embedding")
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(dimension=2, warmup=False, device="cpu"),
        model_factory=lambda *_args, **_kwargs: MinimalModel(),
        torch_module=CpuTorch(),
        model_manager=manager,  # type: ignore[arg-type]
    )

    with pytest.raises(RagEmbeddingError, match="not installed"):
        provider.embed_query("first attempt")
    assert provider.runtime.status.value == "failed"

    manager.installed = True

    assert provider.embed_query("second attempt") == [0.0, 1.0]
    assert provider.runtime.status.value == "ready"
