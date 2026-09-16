from __future__ import annotations

from threading import Event, Thread

import pytest

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.multi_agent.trace import (
    MultiAgentTraceCollector,
    MultiAgentTraceEvent,
)
from backend.agent_core.orchestration.parallel_executor import ParallelTaskGraphExecutor
from backend.agent_core.state import AgentState
from backend.models.agent_tasks import TaskRole
from backend.services.agent_trace_store_service import AgentTraceStoreService
from backend.services.multi_agent_runtime_bridge import _EVENT_MAP
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope, success

TASK_EVENTS = (
    "task_planned",
    "task_ready",
    "task_started",
    "task_progress",
    "task_completed",
    "task_partial",
    "task_failed",
    "task_blocked",
    "task_cancelled",
    "task_skipped",
    "task_retrying",
    "plan_revised",
    "budget_exhausted",
    "artifact_verified",
    "artifact_rejected",
    "workflow_partial",
    "workflow_resumed",
)


@pytest.mark.parametrize("event_type", TASK_EVENTS)
def test_each_task_event_has_runtime_and_bridge_mapping(event_type: str) -> None:
    assert AgentEventType(event_type).value == event_type
    assert _EVENT_MAP[event_type].value == event_type
    event = MultiAgentTraceCollector(run_id="contract-run").emit(
        event_type,
        actor="supervisor",
        status="running",
    )
    assert {
        "event_id",
        "run_id",
        "trace_id",
        "sequence",
        "status",
        "timestamp",
        "task_id",
        "parent_task_id",
        "attempt",
        "plan_revision",
        "usage",
        "reason_code",
    }.issubset(event.payload)


def test_task_started_reaches_sink_before_specialist_finishes() -> None:
    entered = Event()
    release = Event()
    delivered: list[MultiAgentTraceEvent] = []

    def delayed(task):
        entered.set()
        assert release.wait(2)
        return success(task.task_id)

    collector = MultiAgentTraceCollector(run_id="events-run", event_sink=delivered.append)
    worker = Thread(
        target=lambda: ParallelTaskGraphExecutor(
            {TaskRole.DOCUMENT: FunctionExecutor(delayed)}
        ).execute(
            plan=plan(("a",)),
            scope=scope(),
            run_id="events-run",
            collector=collector,
        )
    )
    worker.start()
    assert entered.wait(2)
    assert any(item.event_type == "task_started" for item in delivered)
    assert not any(item.event_type == "task_completed" for item in delivered)
    release.set()
    worker.join(2)

    sequences = [item.sequence for item in delivered]
    assert sequences == list(range(len(sequences)))
    started = next(item for item in delivered if item.event_type == "task_started")
    assert started.payload["event_id"] == f"events-run:{started.sequence}"
    assert started.payload["task_id"] == "a"
    assert started.payload["attempt"] == 1
    assert "usage" in started.payload


def test_live_task_events_persist_with_monotonic_resume_sequence(tmp_path) -> None:
    path = tmp_path / "trace.sqlite3"
    state = AgentState(run_id="persisted-run", trace_id="trace-1", session_id="session-1")
    store = AgentTraceStoreService(storage_path=path)
    first = AgentEvent(
        event_type=AgentEventType.TASK_STARTED,
        run_id=state.run_id,
        trace_id=state.trace_id,
        payload={"task_id": "a", "attempt": 1, "private_text": "must-not-persist"},
    )
    store.append_event(state, first, 0)

    reopened = AgentTraceStoreService(storage_path=path)
    second = AgentEvent(
        event_type=AgentEventType.WORKFLOW_RESUMED,
        run_id=state.run_id,
        trace_id=state.trace_id,
        payload={"reason_code": "task_checkpoint_restored"},
    )
    reopened.append_event(state, second, 0)
    reopened.record(state, (first, second))
    events = reopened.list_events(state.run_id)

    assert [item.sequence for item in events] == [0, 1]
    assert [item.event_type for item in events] == ["task_started", "workflow_resumed"]
    assert "private_text" not in events[0].payload
