from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from backend.rag.model_manager import ModelManager

_model_manager: ModelManager | None = None
_model_manager_lock = Lock()


@dataclass(frozen=True, slots=True)
class RagModelRuntimeHealth:
    ready: bool = False
    error: str = ""


_runtime_health: dict[str, RagModelRuntimeHealth] = {}
_runtime_health_lock = Lock()


def get_rag_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is not None:
        return _model_manager
    with _model_manager_lock:
        if _model_manager is None:
            _model_manager = ModelManager()
        return _model_manager


def close_rag_model_manager() -> None:
    global _model_manager
    with _model_manager_lock:
        _model_manager = None


def get_rag_model_runtime_health(model_id: str) -> RagModelRuntimeHealth:
    with _runtime_health_lock:
        return _runtime_health.get(model_id, RagModelRuntimeHealth())


def set_rag_model_runtime_health(
    model_id: str,
    *,
    ready: bool,
    error: str = "",
) -> RagModelRuntimeHealth:
    health = RagModelRuntimeHealth(ready=ready, error=error[:500])
    with _runtime_health_lock:
        _runtime_health[model_id] = health
    return health


__all__ = [
    "RagModelRuntimeHealth",
    "close_rag_model_manager",
    "get_rag_model_manager",
    "get_rag_model_runtime_health",
    "set_rag_model_runtime_health",
]
