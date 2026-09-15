from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryAgentMemoryStore:
    """Small default memory store used when no persistent backend is injected.

    It keeps Stage 5.6 functional without coupling the multi-agent runtime to a
    specific persistence implementation. A SQLite/Redis/user-profile adapter can
    replace it later through the same ``load``/``save`` contract.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _key(user_id: str | None) -> str:
        return str(user_id or "__anonymous__")

    def load(self, user_id: str | None = None) -> dict[str, Any]:
        return deepcopy(self._items.get(self._key(user_id), {}))

    def save(self, user_id: str | None, result: Any) -> None:
        key = self._key(user_id)
        bucket = self._items.setdefault(key, {})
        history = bucket.setdefault("agent_results", [])
        history.append(result)
        bucket["last_agent_result"] = result


class AgentMemoryAdapter:
    """Adapter for loading and saving shared multi-agent memory."""

    def __init__(self, memory_store=None):
        self.memory_store = memory_store or InMemoryAgentMemoryStore()

    def load(self, user_id: str | None = None) -> dict[str, Any]:
        memory = self.memory_store.load(user_id)
        return dict(memory or {})

    def save(self, result: Any, user_id: str | None = None) -> None:
        self.memory_store.save(user_id, result)


__all__ = ["AgentMemoryAdapter", "InMemoryAgentMemoryStore"]
