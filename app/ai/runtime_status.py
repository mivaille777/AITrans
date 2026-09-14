"""Thread-safe process-wide status for user-facing LLM activity."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from time import monotonic

from app.ai.errors import AIError


@dataclass(frozen=True, slots=True)
class LLMRuntimeSnapshot:
    state: str
    provider: str
    model: str
    detail: str
    active_requests: int


class LLMRuntimeStatus:
    def __init__(self) -> None:
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._active_requests = 0
            self._available = False
            self._provider = ""
            self._model = ""
            self._detail = "LLM API has not been checked yet."
            self._route_key = ""
            self._checked_at = 0.0

    def begin(self, *, provider: str, model: str, route_key: str) -> None:
        with self._lock:
            self._active_requests += 1
            self._provider = provider
            self._model = model
            self._route_key = route_key

    def finish(
        self,
        *,
        success: bool,
        provider: str,
        model: str,
        route_key: str,
        detail: str = "",
    ) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._available = success
            self._provider = provider
            self._model = model
            self._detail = "" if success else (detail or "LLM API request failed.")
            self._route_key = route_key
            self._checked_at = monotonic()

    def record_probe(
        self,
        *,
        success: bool,
        provider: str,
        model: str,
        route_key: str,
        detail: str = "",
    ) -> None:
        with self._lock:
            self._available = success
            self._provider = provider
            self._model = model
            self._detail = "" if success else (detail or "LLM API is unavailable.")
            self._route_key = route_key
            self._checked_at = monotonic()

    def needs_probe(self, route_key: str, *, max_age_seconds: float) -> bool:
        with self._lock:
            return (
                self._active_requests == 0
                and (
                    self._route_key != route_key
                    or self._checked_at <= 0
                    or monotonic() - self._checked_at >= max_age_seconds
                )
            )

    def snapshot(self) -> LLMRuntimeSnapshot:
        with self._lock:
            state = "calling" if self._active_requests > 0 else (
                "available" if self._available else "unavailable"
            )
            return LLMRuntimeSnapshot(
                state=state,
                provider=self._provider,
                model=self._model,
                detail=self._detail,
                active_requests=self._active_requests,
            )


llm_runtime_status = LLMRuntimeStatus()


def _safe_error_detail(exc: BaseException) -> str:
    if isinstance(exc, AIError):
        return str(exc) or "LLM API request failed."
    return "LLM API request failed."


@contextmanager
def track_llm_request(
    *,
    provider: str,
    model: str,
    route_key: str,
) -> Iterator[None]:
    llm_runtime_status.begin(provider=provider, model=model, route_key=route_key)
    try:
        yield
    except GeneratorExit:
        # Cancelling a stream does not mean the provider became unavailable.
        llm_runtime_status.finish(
            success=True,
            provider=provider,
            model=model,
            route_key=route_key,
        )
        raise
    except BaseException as exc:
        llm_runtime_status.finish(
            success=False,
            provider=provider,
            model=model,
            route_key=route_key,
            detail=_safe_error_detail(exc),
        )
        raise
    else:
        llm_runtime_status.finish(
            success=True,
            provider=provider,
            model=model,
            route_key=route_key,
        )


__all__ = [
    "LLMRuntimeSnapshot",
    "LLMRuntimeStatus",
    "llm_runtime_status",
    "track_llm_request",
]
