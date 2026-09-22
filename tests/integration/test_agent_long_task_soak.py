from __future__ import annotations

import asyncio

import pytest

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.models.agent_run import AgentRunStatus, AgentStepRecord
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import TaskStatus
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_run_worker import AgentRunOutcome, AgentRunWorker

_STEP_COUNT = 12


def _step_id(index: int) -> str:
    return f"soak-step-{index:02d}"


def _record_step(store: AgentRunStore, run, index: int) -> None:
    step_id = _step_id(index)
    existing = store.get_step(run.run_id, step_id)
    if existing is not None and existing.status is TaskStatus.SUCCEEDED:
        return
    store.save_step(
        AgentStepRecord(
            task_id=step_id,
            run_id=run.run_id,
            status=TaskStatus.SUCCEEDED,
        )
    )
    store.append_event(
        AgentEvent(
            event_type=AgentEventType.TASK_COMPLETED,
            task_id=run.task_id,
            run_id=run.run_id,
            trace_id=run.trace_id,
            step_id=step_id,
            payload={"soak_index": index},
        ),
        lease_owner=None,
    )


@pytest.mark.asyncio
async def test_long_task_soak_survives_pause_reconnect_and_store_restart(tmp_path) -> None:
    path = tmp_path / "agent_runtime.sqlite3"
    first_store = AgentRunStore(storage_path=path)
    run = AgentRunScheduler(first_store).enqueue(
        goal="Deterministic long-task soak",
        runtime_profile=AgentRuntimeProfile.LONG_TASK,
        task_id="task-long-soak",
        run_id="run-long-soak",
        trace_id="trace-long-soak",
        request_payload={"user_message": "long soak"},
    )

    pause_boundary = asyncio.Event()

    async def first_execution(current, control, recovering):
        assert recovering is False
        assert control.policy.total_timeout_seconds == 1800
        for index in range(4):
            _record_step(first_store, current, index)
        pause_boundary.set()
        while not control.pause_event.is_set():
            await asyncio.sleep(0.005)
        control.pause_at_boundary("soak-pause-boundary")
        raise AssertionError("pause boundary must interrupt execution")

    first_worker = AgentRunWorker(
        first_store,
        first_execution,
        worker_id="soak-worker-a",
        lease_seconds=0.3,
        heartbeat_seconds=0.02,
        poll_seconds=0.01,
    )
    first_task = asyncio.create_task(first_worker.run_once())
    await asyncio.wait_for(pause_boundary.wait(), timeout=15)
    requested = AgentRunScheduler(first_store).pause(run.run_id)
    assert requested.status is AgentRunStatus.PAUSE_REQUESTED
    paused = await asyncio.wait_for(first_task, timeout=15)
    assert paused is not None and paused.status is AgentRunStatus.PAUSED

    pre_restart_events = first_store.list_events(run.run_id)
    assert len(pre_restart_events) == 4
    disconnect_cursor = pre_restart_events[-1].sequence
    original_budget_used = paused.budget_used_ms
    first_store.close()

    # Backend restart: reopen the same durable store. Identity and completed
    # steps must survive without relying on process-local memory.
    restarted_store = AgentRunStore(storage_path=path)
    restored = restarted_store.get_run(run.run_id)
    assert restored is not None
    assert restored.status is AgentRunStatus.PAUSED
    assert restored.task_id == "task-long-soak"
    assert restored.run_id == "run-long-soak"
    assert restored.trace_id == "trace-long-soak"
    assert all(
        restarted_store.get_step(run.run_id, _step_id(index)).status is TaskStatus.SUCCEEDED
        for index in range(4)
    )
    assert restarted_store.list_events_after(
        run.run_id, after_sequence=disconnect_cursor
    ) == ()

    resumed = AgentRunScheduler(restarted_store).resume(run.run_id)
    assert resumed.status is AgentRunStatus.RECOVERING

    executed_after_restart: list[str] = []

    async def resumed_execution(current, control, recovering):
        assert recovering is True
        assert current.run_id == "run-long-soak"
        assert current.trace_id == "trace-long-soak"
        for index in range(_STEP_COUNT):
            step_id = _step_id(index)
            existing = restarted_store.get_step(current.run_id, step_id)
            if existing is not None and existing.status is TaskStatus.SUCCEEDED:
                continue
            executed_after_restart.append(step_id)
            _record_step(restarted_store, current, index)
            await asyncio.sleep(0)
        return AgentRunOutcome(
            status=AgentRunStatus.COMPLETED,
            result={
                "output_text": "long-task soak completed",
                "completed_steps": _STEP_COUNT,
            },
        )

    second_worker = AgentRunWorker(
        restarted_store,
        resumed_execution,
        worker_id="soak-worker-b",
        lease_seconds=0.3,
        heartbeat_seconds=0.02,
        poll_seconds=0.01,
    )
    completed = await second_worker.run_once()
    assert completed is not None
    assert completed.status is AgentRunStatus.COMPLETED
    assert completed.run_id == run.run_id
    assert completed.trace_id == run.trace_id
    assert completed.budget_used_ms >= original_budget_used

    # Simulated frontend reconnect: replay only events after the last sequence
    # observed before navigation/disconnect.
    replay = restarted_store.list_events_after(
        run.run_id, after_sequence=disconnect_cursor
    )
    assert [event.sequence for event in replay] == list(
        range(disconnect_cursor + 1, disconnect_cursor + 1 + len(replay))
    )
    assert [event.step_id for event in replay] == [
        _step_id(index) for index in range(4, _STEP_COUNT)
    ]
    assert executed_after_restart == [
        _step_id(index) for index in range(4, _STEP_COUNT)
    ]

    all_events = restarted_store.list_events(run.run_id)
    completed_step_ids = [
        event.step_id
        for event in all_events
        if event.event_type is AgentEventType.TASK_COMPLETED
    ]
    assert len(completed_step_ids) == _STEP_COUNT
    assert len(set(completed_step_ids)) == _STEP_COUNT
    assert restarted_store.get_run_result(run.run_id) == {
        "completed_steps": _STEP_COUNT,
        "output_text": "long-task soak completed",
    }
    assert restarted_store.get_lease(run.run_id) is None
