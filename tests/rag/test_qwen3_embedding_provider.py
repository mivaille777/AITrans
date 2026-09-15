from __future__ import annotations

import math
from typing import Any

import pytest

from backend.rag.config import RagEmbeddingConfig
from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
from backend.rag.embeddings.runtime import EmbeddingRuntimeStatus
from backend.rag.exceptions import RagConfigurationError, RagEmbeddingError


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def memory_allocated(self) -> int:
        return 128 * 1024**2

    def memory_reserved(self) -> int:
        return 256 * 1024**2


class FakeTorch:
    def __init__(self, cuda_available: bool) -> None:
        self.cuda = FakeCuda(cuda_available)


class FakeModel:
    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.output_override: list[list[float]] | None = None
        self.error: Exception | None = None

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        if self.error is not None:
            raise self.error
        if self.output_override is not None:
            return self.output_override
        return [[float(index) for index in range(self.dimension)] for _ in texts]


class Factory:
    def __init__(
        self, model: FakeModel | None = None, error: Exception | None = None
    ) -> None:
        self.model = model or FakeModel()
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeModel:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.model


def make_provider(
    *,
    model: FakeModel | None = None,
    factory: Factory | None = None,
    device: str = "auto",
    cuda_available: bool = False,
    warmup: bool = False,
    batch_size: int = 3,
    model_path: str = "",
    local_files_only: bool = False,
) -> tuple[Qwen3EmbeddingProvider, Factory]:
    selected_factory = factory or Factory(model)
    provider = Qwen3EmbeddingProvider(
        RagEmbeddingConfig(
            dimension=4,
            device=device,
            warmup=warmup,
            batch_size=batch_size,
            model_path=model_path,
            local_files_only=local_files_only,
        ),
        model_factory=selected_factory,
        torch_module=FakeTorch(cuda_available),
    )
    return provider, selected_factory


def test_model_loads_once_and_is_reused() -> None:
    provider, factory = make_provider()

    provider.embed_query("first")
    provider.embed_query("second")
    provider.embed_documents(["doc one", "doc two"])

    assert len(factory.calls) == 1
    assert provider.runtime.status is EmbeddingRuntimeStatus.READY
    assert provider.runtime.load_time_ms >= 0


def test_query_uses_query_prompt_and_documents_do_not() -> None:
    model = FakeModel()
    provider, _ = make_provider(model=model)

    provider.embed_query("question")
    provider.embed_documents(["document"])

    query_call, document_call = model.calls
    assert query_call[1]["prompt_name"] == "query"
    assert "prompt_name" not in document_call[1]


def test_encode_options_use_normalization_and_configured_batch_size() -> None:
    model = FakeModel()
    provider, _ = make_provider(model=model, batch_size=7)

    provider.embed_query("question")
    provider.embed_documents(["one", "two"])

    for _texts, kwargs in model.calls:
        assert kwargs["normalize_embeddings"] is True
        assert kwargs["batch_size"] == 7
        assert kwargs["convert_to_numpy"] is True
        assert kwargs["show_progress_bar"] is False


def test_output_dimension_and_batch_count_are_validated() -> None:
    provider, _ = make_provider()

    assert len(provider.embed_query("question")) == 4
    assert len(provider.embed_documents(["one", "two"])) == 2


def test_non_finite_vector_is_rejected() -> None:
    model = FakeModel()
    model.output_override = [[0.0, 1.0, math.nan, 3.0]]
    provider, _ = make_provider(model=model)

    with pytest.raises(RagEmbeddingError, match="non-finite"):
        provider.embed_query("question")


def test_wrong_dimension_is_rejected() -> None:
    model = FakeModel(dimension=3)
    provider, _ = make_provider(model=model)

    with pytest.raises(RagEmbeddingError, match="dimension mismatch"):
        provider.embed_query("question")


def test_load_failure_sets_failed_state_and_is_not_retried() -> None:
    factory = Factory(error=RuntimeError("load failed"))
    provider, _ = make_provider(factory=factory)

    with pytest.raises(RagEmbeddingError, match="load failed"):
        provider.embed_query("question")
    with pytest.raises(RagEmbeddingError, match="load failed"):
        provider.embed_query("retry")

    assert provider.runtime.status is EmbeddingRuntimeStatus.FAILED
    assert provider.runtime.last_error == "load failed"
    assert len(factory.calls) == 1


def test_warmup_failure_sets_failed_state() -> None:
    model = FakeModel()
    model.error = RuntimeError("warmup failed")
    provider, _ = make_provider(model=model, warmup=True)

    with pytest.raises(RagEmbeddingError, match="warmup failed"):
        provider.embed_query("question")

    assert provider.runtime.status is EmbeddingRuntimeStatus.FAILED


def test_warmup_runs_once_with_query_prompt() -> None:
    model = FakeModel()
    provider, factory = make_provider(model=model, warmup=True)

    provider.embed_query("first")
    provider.embed_query("second")

    assert len(factory.calls) == 1
    assert [call[0] for call in model.calls] == [["warmup"], ["first"], ["second"]]
    assert all(call[1]["prompt_name"] == "query" for call in model.calls)


def test_auto_device_falls_back_to_cpu() -> None:
    provider, factory = make_provider(device="auto", cuda_available=False)

    provider.embed_query("question")

    assert factory.calls[0][1]["device"] == "cpu"
    assert provider.runtime.device == "cpu"


def test_auto_device_selects_cuda_and_records_memory() -> None:
    provider, factory = make_provider(device="auto", cuda_available=True)

    provider.embed_query("question")

    assert factory.calls[0][1]["device"] == "cuda"
    assert provider.runtime.allocated_vram_mb == pytest.approx(128)
    assert provider.runtime.reserved_vram_mb == pytest.approx(256)


def test_explicit_cuda_fails_when_unavailable() -> None:
    provider, _ = make_provider(device="cuda", cuda_available=False)

    with pytest.raises(RagConfigurationError, match="not available"):
        provider.embed_query("question")

    assert provider.runtime.status is EmbeddingRuntimeStatus.FAILED


def test_model_path_and_local_files_only_are_forwarded() -> None:
    provider, factory = make_provider(
        model_path="D:/models/qwen3",
        local_files_only=True,
    )

    provider.embed_query("question")

    args, kwargs = factory.calls[0]
    assert args == ("D:/models/qwen3",)
    assert kwargs["local_files_only"] is True


def test_empty_document_batch_does_not_load_model() -> None:
    provider, factory = make_provider()

    assert provider.embed_documents([]) == []
    assert factory.calls == []
    assert provider.runtime.status is EmbeddingRuntimeStatus.UNINITIALIZED
