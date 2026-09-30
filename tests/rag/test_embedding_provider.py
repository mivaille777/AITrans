from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings import EmbeddingProvider, Qwen3EmbeddingProvider
from backend.rag.embeddings.base import EmbeddingFingerprint
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


def test_qwen3_provider_satisfies_embedding_protocol(tmp_path: Path) -> None:
    (tmp_path / "model.safetensors").write_bytes(b"fake model weights")
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(dimension=2, warmup=False, model_path=str(tmp_path)),
        model_factory=lambda *_args, **_kwargs: MinimalModel(),
        torch_module=CpuTorch(),
    )

    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimension == 2
    assert provider.model_name == "Qwen/Qwen3-Embedding-0.6B"
    assert provider.fingerprint.as_dict() == {
        "schema_version": 1,
        "model_id": "Qwen/Qwen3-Embedding-0.6B",
        "dimension": 2,
        "normalized": True,
        "query_prefix": "query",
        "document_prefix": "",
        "model_revision": provider.fingerprint.model_revision,
        "digest": provider.fingerprint.digest,
    }
    assert provider.fingerprint.model_revision.startswith("sha256:")


def test_same_model_name_and_dimension_detects_changed_weights(tmp_path: Path) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"old weights")
    config = RagEmbeddingConfig(dimension=2, model_path=str(tmp_path))
    first = Qwen3EmbeddingProvider(config).fingerprint
    weights.write_bytes(b"new weights")
    second = Qwen3EmbeddingProvider(config).fingerprint
    assert first.model_id == second.model_id
    assert first.dimension == second.dimension
    assert first.digest != second.digest


def test_fingerprint_is_location_independent_and_covers_token_limit(
    tmp_path: Path,
) -> None:
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    for directory in (first_dir, second_dir):
        directory.mkdir()
        (directory / "model.safetensors").write_bytes(b"identical weights")
        (directory / "config.json").write_text('{"hidden_size":2}', encoding="utf-8")
    first_config = RagEmbeddingConfig(dimension=2, model_path=str(first_dir))
    second_config = first_config.model_copy(update={"model_path": str(second_dir)})
    first = Qwen3EmbeddingProvider(first_config).fingerprint
    assert first == Qwen3EmbeddingProvider(second_config).fingerprint
    changed = second_config.model_copy(update={"max_input_tokens": 128})
    assert first.digest != Qwen3EmbeddingProvider(changed).fingerprint.digest


def test_embedding_fingerprint_changes_when_prompt_prefix_changes() -> None:
    base = EmbeddingFingerprint(
        model_id="model-v1",
        dimension=1024,
        normalized=True,
        query_prefix="query",
        document_prefix="",
    )
    changed = EmbeddingFingerprint(
        model_id="model-v1",
        dimension=1024,
        normalized=True,
        query_prefix="query-v2",
        document_prefix="",
    )

    assert base.digest != changed.digest


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


def test_missing_managed_embedding_can_recover_after_model_install(
    tmp_path: Path,
) -> None:
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
