from __future__ import annotations

from threading import Lock

from app.infrastructure.paths import writable_config_dir
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository

DEFAULT_MEMORY_FILENAME = "memory.sqlite3"

_coordinator: MemoryCoordinator | None = None
_lock = Lock()


def get_memory_coordinator() -> MemoryCoordinator:
    global _coordinator
    if _coordinator is not None:
        return _coordinator
    with _lock:
        if _coordinator is None:
            _coordinator = MemoryCoordinator(
                SQLiteMemoryRepository(writable_config_dir() / DEFAULT_MEMORY_FILENAME)
            )
        return _coordinator


def close_memory_coordinator() -> None:
    global _coordinator
    with _lock:
        _coordinator = None


__all__ = [
    "DEFAULT_MEMORY_FILENAME",
    "close_memory_coordinator",
    "get_memory_coordinator",
]
