from __future__ import annotations

from typing import get_args

from backend.agent_core.events import AgentEventType
from backend.models.agent_tools import AgentTraceEvent, AgentTraceEventType


def test_agent_trace_event_api_contract_matches_runtime_event_enum() -> None:
    runtime_events = {event.value for event in AgentEventType}
    api_events = set(get_args(AgentTraceEventType))

    assert api_events == runtime_events


def test_every_runtime_event_serializes_through_trace_response_model() -> None:
    for index, event_type in enumerate(AgentEventType):
        event = AgentTraceEvent(
            sequence=index,
            event_type=event_type.value,
            timestamp="2026-09-15T00:00:00+00:00",
            run_id="run-contract",
            trace_id="trace-contract",
            elapsed_ms=index,
            payload={"contract_test": True},
        )
        assert event.event_type == event_type.value
