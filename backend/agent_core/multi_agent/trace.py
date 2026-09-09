from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class MultiAgentTraceEvent:
    """Privacy-bounded event emitted by the Stage 5 multi-agent runtime."""

    sequence: int
    event_type: str
    actor: str
    status: str
    timestamp: str
    elapsed_ms: int
    payload: dict[str, Any] = field(default_factory=dict)


class MultiAgentTraceCollector:
    """Collect a bounded execution trace for Supervisor and specialized agents.

    The collector intentionally stores orchestration metadata only. User task text,
    knowledge context text, and agent output text must not be placed in event payloads.
    """

    def __init__(self, *, run_id: str | None = None, trace_id: str | None = None) -> None:
        suffix = uuid4().hex
        self.run_id = run_id or f"multi-run-{suffix}"
        self.trace_id = trace_id or f"multi-trace-{suffix}"
        self._started_at = perf_counter()
        self._events: list[MultiAgentTraceEvent] = []

    def emit(
        self,
        event_type: str,
        *,
        actor: str,
        status: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> MultiAgentTraceEvent:
        event = MultiAgentTraceEvent(
            sequence=len(self._events),
            event_type=str(event_type or "event"),
            actor=str(actor or "runtime"),
            status=str(status or "info"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=max(0, int((perf_counter() - self._started_at) * 1000)),
            payload=dict(payload or {}),
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[MultiAgentTraceEvent, ...]:
        return tuple(self._events)

    @property
    def total_duration_ms(self) -> int:
        if not self._events:
            return 0
        return self._events[-1].elapsed_ms


__all__ = ["MultiAgentTraceCollector", "MultiAgentTraceEvent"]
