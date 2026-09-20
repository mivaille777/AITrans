from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
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

    def __init__(
        self,
        *,
        run_id: str | None = None,
        trace_id: str | None = None,
        event_sink: Callable[[MultiAgentTraceEvent], None] | None = None,
    ) -> None:
        suffix = uuid4().hex
        self.run_id = run_id or f"multi-run-{suffix}"
        self.trace_id = trace_id or f"multi-trace-{suffix}"
        self._started_at = perf_counter()
        self._events: list[MultiAgentTraceEvent] = []
        self._event_sink = event_sink
        self._lock = RLock()

    def emit(
        self,
        event_type: str,
        *,
        actor: str,
        status: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> MultiAgentTraceEvent:
        with self._lock:
            sequence = len(self._events)
            timestamp = datetime.now(UTC).isoformat()
            normalized_status = str(status or "info")
            normalized_payload = dict(payload or {})
            normalized_payload.setdefault("event_id", f"{self.run_id}:{sequence}")
            normalized_payload.setdefault("run_id", self.run_id)
            normalized_payload.setdefault("trace_id", self.trace_id)
            normalized_payload.setdefault("sequence", sequence)
            normalized_payload.setdefault("status", normalized_status)
            normalized_payload.setdefault("timestamp", timestamp)
            normalized_payload.setdefault("task_id", "")
            normalized_payload.setdefault("parent_task_id", "")
            normalized_payload.setdefault("attempt", 0)
            normalized_payload.setdefault("plan_revision", 0)
            normalized_payload.setdefault("usage", {})
            normalized_payload.setdefault("reason_code", "")
            event = MultiAgentTraceEvent(
                sequence=sequence,
                event_type=str(event_type or "event"),
                actor=str(actor or "runtime"),
                status=normalized_status,
                timestamp=timestamp,
                elapsed_ms=max(0, int((perf_counter() - self._started_at) * 1000)),
                payload=normalized_payload,
            )
            self._events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
        return event

    @property
    def events(self) -> tuple[MultiAgentTraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def total_duration_ms(self) -> int:
        with self._lock:
            if not self._events:
                return 0
            return self._events[-1].elapsed_ms


__all__ = ["MultiAgentTraceCollector", "MultiAgentTraceEvent"]
