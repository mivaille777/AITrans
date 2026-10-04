from __future__ import annotations

import json
from collections import OrderedDict
from hashlib import sha256
from threading import RLock
from time import monotonic


def cache_key(*, query: str, scope, generations, model, query_version: str) -> str:
    payload = [query, sorted(scope) if scope is not None else None,
               generations, model, query_version]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EmbeddingCache:
    """Bounded, versioned immutable vectors; scope is part of every key."""
    def __init__(self, max_entries: int, *, ttl_seconds: float = 300, clock=monotonic):
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("cache bounds must be positive")
        self.max_entries, self.ttl_seconds, self.clock = max_entries, ttl_seconds, clock
        self._items = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> tuple[float, ...] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires, vector = item
            if self.clock() >= expires:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return vector

    def put(self, key: str, vector) -> None:
        with self._lock:
            self._items[key] = (self.clock() + self.ttl_seconds, tuple(vector))
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
