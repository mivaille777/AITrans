from __future__ import annotations

import atexit
import importlib
import multiprocessing
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Condition, Event, Lock, local
from time import monotonic
from typing import Any

from backend.rag.exceptions import RagRetrievalError

_cancellation: ContextVar[Callable[[], bool] | None] = ContextVar("rag_inference_cancellation", default=None)


@contextmanager
def inference_cancellation(event: Event | Callable[[], bool]):
    token = _cancellation.set(event if callable(event) else event.is_set)
    try:
        yield
    finally:
        _cancellation.reset(token)


def _error_text(exc: BaseException | None) -> str:
    messages = []
    while exc is not None and len(messages) < 4:
        messages.append(f"{type(exc).__name__}: {exc}")
        exc = exc.__cause__
    return " <- caused by: ".join(messages)[:4000]


def _serve(connection, factory_path: str, options: dict[str, Any]) -> None:
    provider = None
    try:
        module, name = factory_path.rsplit(":", 1)
        provider = getattr(importlib.import_module(module), name)(**options)
        while True:
            method, args, kwargs = connection.recv()
            started = monotonic()
            try:
                value = getattr(provider, method)
                result = value(*args, **kwargs) if callable(value) else value
                connection.send((True, result, (monotonic() - started) * 1000))
            except Exception as exc:  # noqa: BLE001 - preserve model errors across the process boundary
                connection.send((False, _error_text(exc), (monotonic() - started) * 1000))
    except (EOFError, BrokenPipeError):
        pass  # The owner closed its pipe or terminated this worker.
    except Exception as exc:  # noqa: BLE001 - report worker initialization failure to its owner
        try:
            connection.send((False, _error_text(exc), None))
        except (EOFError, BrokenPipeError, OSError):
            pass  # No receiver remains to consume an initialization error.
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        connection.close()


def create_model_provider(kind: str, config: dict[str, Any]):
    from backend.rag.config import (
        RagEmbeddingConfig,
        RagRerankerConfig,
        RagVisualRetrievalConfig,
    )
    from backend.rag.model_manager import ModelManager

    if kind == "embedding":
        from backend.rag.embeddings.qwen3 import Qwen3EmbeddingProvider
        return Qwen3EmbeddingProvider(RagEmbeddingConfig.model_validate(config), model_manager=ModelManager())
    if kind == "reranker":
        from backend.rag.rerankers.qwen3 import Qwen3RerankerProvider
        return Qwen3RerankerProvider(RagRerankerConfig.model_validate(config), model_manager=ModelManager())
    if kind == "visual":
        from backend.rag.visual_retrieval import ColPaliEngineVisualEmbeddingProvider
        return ColPaliEngineVisualEmbeddingProvider(RagVisualRetrievalConfig.model_validate(config))
    raise ValueError(f"unsupported inference worker kind: {kind}")


class ProcessInferenceProvider:
    """One reusable model process, killed and joined on cancellation or timeout."""

    def __init__(self, provider: Any, *, kind: str, timeout_seconds: float,
                 factory_path: str = "backend.rag.inference_worker:create_model_provider",
                 factory_options: dict[str, Any] | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("inference timeout must be positive")
        self._provider = provider
        self._factory_path = factory_path
        self._options = factory_options if factory_options is not None else {
            "kind": kind, "config": provider._config.model_dump(mode="json"),
        }
        self._timeout = timeout_seconds
        self._lock = Lock()
        self._queue_changed = Condition()
        self._pending: deque[object] = deque()
        self._call_metrics = local()
        self._process = None
        self._connection = None
        self._closed = False
        atexit.register(self.close)

    def __getattr__(self, name: str):
        # Identity/fingerprint checks stay in the owner and never load a model.
        return getattr(self._provider, name)

    def _stop(self) -> None:
        process, connection = self._process, self._connection
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            if process.is_alive():
                raise RagRetrievalError("inference worker could not be terminated")
            process.close()
        if connection is not None:
            connection.close()
        self._process = self._connection = None

    def _call(self, method: str, *args, **kwargs):
        started = monotonic()
        self._call_metrics.value = {}
        deadline = started + self._timeout
        cancelled = _cancellation.get()
        ticket = object()
        with self._queue_changed:
            self._pending.append(ticket)
            try:
                while True:
                    if cancelled is not None and cancelled():
                        raise RagRetrievalError("inference cancelled while waiting for worker")
                    if monotonic() >= deadline:
                        raise TimeoutError("inference worker queue deadline exceeded")
                    if self._pending[0] is ticket and self._lock.acquire(blocking=False):
                        break
                    self._queue_changed.wait(timeout=0.02)
            finally:
                self._pending.remove(ticket)
                self._queue_changed.notify_all()
        try:
            self._call_metrics.value = {"queue_ms": (monotonic() - started) * 1000}
            if self._closed:
                raise RagRetrievalError("inference worker is closed")
            if cancelled is not None and cancelled():
                raise RagRetrievalError("inference cancelled")
            if self._process is None:
                config = self._options.get("config")
                kind = self._options.get("kind")
                if config is not None and not config.get("model_path") and kind in {"embedding", "reranker"}:
                    if kind == "embedding":
                        _fingerprint = self._provider.fingerprint
                        config["model_path"] = self._provider._resolved_model_path
                    else:
                        manager = self._provider._model_manager
                        if manager is not None:
                            config["model_path"] = str(manager.get_model_path("qwen3-reranker-0.6b"))
                    if config.get("model_path"):
                        config["local_files_only"] = True
                context = multiprocessing.get_context("spawn")
                self._connection, child = context.Pipe()
                self._process = context.Process(target=_serve,
                    args=(child, self._factory_path, self._options), daemon=True)
                try:
                    self._process.start()
                except Exception:  # Release an unsuccessful spawn and preserve its error.
                    if self._process.pid is None:
                        self._process.close()
                        self._connection.close()
                        self._process = self._connection = None
                    else:
                        self._stop()
                    raise
                finally:
                    child.close()
            try:
                self._connection.send((method, args, kwargs))
                while True:
                    if cancelled is not None and cancelled():
                        self._stop()
                        raise RagRetrievalError("inference cancelled; worker terminated")
                    if monotonic() >= deadline:
                        self._stop()
                        raise TimeoutError("inference deadline exceeded; worker terminated")
                    if self._connection.poll(min(0.02, max(0.0, deadline - monotonic()))):
                        success, value, execution_ms = self._connection.recv()
                        self._call_metrics.value["execution_ms"] = execution_ms
                        if cancelled is not None and cancelled():
                            self._stop()
                            raise RagRetrievalError("inference cancelled; late result rejected")
                        if not success:
                            raise RagRetrievalError(value)
                        return value
                    if not self._process.is_alive():
                        self._stop()
                        raise RagRetrievalError("inference worker exited without a result")
            except TimeoutError:
                raise
            except (EOFError, BrokenPipeError, OSError) as exc:
                self._stop()
                raise RagRetrievalError("inference worker connection failed") from exc
        finally:
            self._call_metrics.value["total_ms"] = (monotonic() - started) * 1000
            self._lock.release()
            with self._queue_changed:
                self._queue_changed.notify_all()

    @property
    def last_call_timings(self) -> dict[str, float | None]:
        """Per-thread metrics; execution includes lazy model loading in the child."""
        return dict(getattr(self._call_metrics, "value", {}))

    def embed_query(self, query):
        return self._call("embed_query", query)

    def embed_documents(self, texts):
        return self._call("embed_documents", texts)

    def embed_images(self, paths):
        return self._call("embed_images", paths)

    def rerank(self, query, candidates, *, top_k):
        return self._call("rerank", query, candidates, top_k=top_k)

    @property
    def runtime(self):
        return self._provider.runtime if self._process is None else self._call("runtime")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop()
        atexit.unregister(self.close)
