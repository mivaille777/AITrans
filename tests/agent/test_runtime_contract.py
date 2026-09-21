from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState, migrate_agent_state_payload
from backend.models.agent_run import (
    AgentRunRecord,
    AgentRunStatus,
    AgentStepRecord,
    AgentToolCallRecord,
    InvalidRunTransitionError,
    transition_run,
)
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord


def _run(status: AgentRunStatus = AgentRunStatus.QUEUED) -> AgentRunRecord:
    return AgentRunRecord(
        task_id="task-contract",
        run_id="run-contract",
        trace_id="trace-contract",
        runtime_profile=AgentRuntimeProfile.INTERACTIVE,
        status=status,
    )


def test_rt_c01_run_status_allows_only_declared_transitions() -> None:
    running = transition_run(_run(), AgentRunStatus.RUNNING)
    completed = transition_run(running, AgentRunStatus.COMPLETED)

    assert running.status is AgentRunStatus.RUNNING
    assert running.started_at is not None
    assert completed.status is AgentRunStatus.COMPLETED
    assert completed.finished_at is not None
    with pytest.raises(InvalidRunTransitionError, match="completed -> running"):
        transition_run(completed, AgentRunStatus.RUNNING)


@pytest.mark.parametrize("missing", ["task_id", "run_id", "trace_id", "runtime_profile"])
def test_rt_c02_run_requires_every_correlation_field(missing: str) -> None:
    payload = {
        "task_id": "task-contract",
        "run_id": "run-contract",
        "trace_id": "trace-contract",
        "runtime_profile": "interactive",
    }
    payload.pop(missing)

    with pytest.raises(ValidationError):
        AgentRunRecord.model_validate(payload)


def test_rt_c03_step_is_bound_to_exactly_one_run() -> None:
    step = AgentStepRecord(
        task_id="step-context",
        run_id="run-contract",
    )

    assert step.step_id == "step-context"
    assert step.run_id == "run-contract"
    assert step.model_dump()["step_id"] == "step-context"
    with pytest.raises(ValidationError):
        AgentStepRecord(task_id="step-context", run_id="")


@pytest.mark.parametrize("missing", ["run_id", "step_id", "tool_call_id"])
def test_rt_c04_tool_call_requires_run_step_and_call_identity(missing: str) -> None:
    payload = {
        "run_id": "run-contract",
        "step_id": "step-context",
        "tool_call_id": "tool-call-contract",
        "tool_name": "knowledge_search",
        "effect": "read",
        "arguments_hash": "arguments-hash",
        "idempotency_key": "idempotency-key",
        "timeout_ms": 20_000,
    }
    payload.pop(missing)

    with pytest.raises(ValidationError):
        AgentToolCallRecord.model_validate(payload)


def test_runtime_task_state_and_event_share_correlation_contract() -> None:
    task = AgentTaskRecord(task_id="task-contract", goal="Freeze runtime contracts")
    state = AgentState(task_id=task.task_id, runtime_profile="long_task")
    event = AgentEvent(
        event_type=AgentEventType.AGENT_START,
        task_id=state.task_id,
        run_id=state.run_id,
        trace_id=state.trace_id,
        sequence=0,
    )

    assert state.execution.task_id == task.task_id
    assert state.execution.runtime_profile is AgentRuntimeProfile.LONG_TASK
    assert event.event_id.startswith("event-")
    assert event.task_id == state.task_id
    assert event.run_id == state.run_id
    assert event.trace_id == state.trace_id


def test_legacy_agent_state_gets_stable_runtime_contract_defaults() -> None:
    migrated = migrate_agent_state_payload(
        {
            "run_id": "run-legacy",
            "trace_id": "trace-legacy",
            "graph_version": "reading-agent-v1",
            "state_schema_version": 1,
        }
    )

    assert migrated["task_id"] == "task-legacy"
    assert migrated["runtime_profile"] == "interactive"
