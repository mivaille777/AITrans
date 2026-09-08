from __future__ import annotations

from typing import Any


class AgentMemoryAdapter:
    """Adapter for loading and saving agent memory."""

    def __init__(self, memory_store=None):
        self.memory_store = memory_store

    def load(self, user_id: str | None = None) -> dict[str, Any]:
        if self.memory_store is None:
            return {}
        return self.memory_store.load(user_id) or {}

    def save(self, result: Any, user_id: str | None = None) -> None:
        if self.memory_store is None:
            return
        self.memory_store.save(user_id, result)


__all__ = ["AgentMemoryAdapter"]
