from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.api.agent import _trace_event
from backend.models.agent_tools import AgentTraceEvent, AgentTraceEventType
from backend.services.agent_trace_store_service import _redacted_payload

EVENT_TYPES = tuple(AgentEventType)


def test_agent_trace_event_api_contract_matches_runtime_event_enum() -> None:
    runtime_events = tuple(event.value for event in EVENT_TYPES)
    api_events = get_args(AgentTraceEventType)

    assert api_events == runtime_events


def test_agent_trace_event_json_schema_exposes_every_runtime_event() -> None:
    event_schema = AgentTraceEvent.model_json_schema()["properties"]["event_type"]

    assert event_schema["enum"] == [event.value for event in EVENT_TYPES]


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda event: event.value)
def test_each_runtime_event_serializes_through_trace_response_model(
    event_type: AgentEventType,
) -> None:
    event = AgentTraceEvent(
        sequence=7,
        event_type=event_type.value,
        timestamp="2026-09-15T00:00:00+00:00",
        run_id="run-contract",
        trace_id="trace-contract",
        elapsed_ms=21,
        payload={"contract_test": event_type.value},
    )

    assert event.model_dump(mode="json") == {
        "sequence": 7,
        "event_type": event_type.value,
        "timestamp": "2026-09-15T00:00:00+00:00",
        "run_id": "run-contract",
        "trace_id": "trace-contract",
        "elapsed_ms": 21,
        "payload": {"contract_test": event_type.value},
    }


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda event: event.value)
def test_each_runtime_event_converts_to_api_trace_event(
    event_type: AgentEventType,
) -> None:
    runtime_event = AgentEvent(
        event_type=event_type,
        timestamp="2026-09-15T00:00:00+00:00",
        run_id="run-contract",
        trace_id="trace-contract",
        elapsed_ms=21,
        payload={"contract_test": event_type.value},
    )

    trace_event = _trace_event(7, runtime_event)

    assert trace_event.model_dump(mode="json") == {
        "sequence": 7,
        "event_type": event_type.value,
        "timestamp": "2026-09-15T00:00:00+00:00",
        "run_id": "run-contract",
        "trace_id": "trace-contract",
        "elapsed_ms": 21,
        "payload": {"contract_test": event_type.value},
    }


def test_agent_trace_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        AgentTraceEvent(
            sequence=0,
            event_type="unknown_event",
            timestamp="2026-09-15T00:00:00+00:00",
        )


def test_knowledge_tool_trace_keeps_aggregate_sizes_without_content() -> None:
    event = AgentEvent(
        event_type=AgentEventType.TOOL_RESULT,
        timestamp="2026-09-15T00:00:00+00:00",
        run_id="run-metrics",
        trace_id="trace-metrics",
        elapsed_ms=21,
        payload={
            "tool_name": "search_knowledge_base",
            "output_text": "private snippet text",
            "output_chars": 19,
            "candidate_count": 8,
            "data": {"results": ["private"]},
        },
    )

    redacted = _redacted_payload(event)

    assert redacted == {
        "tool_name": "search_knowledge_base",
        "output_chars": 19,
        "candidate_count": 8,
    }
