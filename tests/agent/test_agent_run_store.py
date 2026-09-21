from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.models.agent_run import (
    AgentRunRecord,
    AgentRunStatus,
    AgentStepRecord,
    AgentToolCallRecord,
    InvalidRunTransitionError,
)
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_run_store import (
    AgentRunStore,
    AgentRunStoreConflictError,
)


def _task() -> AgentTaskRecord:
    return AgentTaskRecord(
        task_id="task-store",
        goal="Persist a durable Agent run",
        workspace_id="workspace-1",
    )


def _run() -> AgentRunRecord:
    return AgentRunRecord(
        task_id="task-store",
        run_id="run-store",
        trace_id="trace-store",
        runtime_profile=AgentRuntimeProfile.LONG_TASK,
    )


def _store(tmp_path) -> AgentRunStore:
    return AgentRunStore(storage_path=tmp_path / "agent_runtime.sqlite3")


def test_rt_s01_creates_task_run_and_runtime_schema(tmp_path) -> None:
    store = _store(tmp_path)
    task, run = store.create_task_and_run(_task(), _run())

    assert store.get_task(task.task_id) == task
    assert store.get_run(run.run_id) == run

    with sqlite3.connect(store.storage_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])

    assert {
        "agent_tasks",
        "agent_runs",
        "agent_steps",
        "agent_tool_calls",
        "agent_runtime_events",
        "agent_worker_leases",
    } <= tables
    assert journal_mode.casefold() == "wal"


def test_rt_s02_run_survives_reopened_store(tmp_path) -> None:
    path = tmp_path / "agent_runtime.sqlite3"
    first = AgentRunStore(storage_path=path)
    expected_task = _task()
    expected_run = _run()
    first.create_task_and_run(expected_task, expected_run)
    first.close()

    reopened = AgentRunStore(storage_path=path)

    assert reopened.get_task("task-store") == expected_task
    assert reopened.get_run("run-store") == expected_run


def test_rt_s03_rejects_illegal_and_stale_status_transitions(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task_and_run(_task(), _run())
    running = store.transition_run(
        "run-store",
        expected_status=AgentRunStatus.QUEUED,
        target_status=AgentRunStatus.RUNNING,
    )
    completed = store.transition_run(
        "run-store",
        expected_status=AgentRunStatus.RUNNING,
        target_status=AgentRunStatus.COMPLETED,
    )

    assert running.status is AgentRunStatus.RUNNING
    assert completed.status is AgentRunStatus.COMPLETED
    with pytest.raises(InvalidRunTransitionError):
        store.transition_run(
            "run-store",
            expected_status=AgentRunStatus.COMPLETED,
            target_status=AgentRunStatus.RUNNING,
        )
    with pytest.raises(AgentRunStoreConflictError):
        store.transition_run(
            "run-store",
            expected_status=AgentRunStatus.RUNNING,
            target_status=AgentRunStatus.FAILED,
        )
    assert store.get_run("run-store").status is AgentRunStatus.COMPLETED


def test_rt_s04_one_hundred_concurrent_claims_have_exactly_one_owner(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task_and_run(_task(), _run())

    def claim(index: int):
        return store.claim_run(lease_owner=f"worker-{index}", lease_seconds=30)

    with ThreadPoolExecutor(max_workers=20) as executor:
        claims = tuple(executor.map(claim, range(100)))

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert winners[0].run_id == "run-store"
    lease = store.get_lease("run-store")
    assert lease is not None
    assert lease.lease_owner.startswith("worker-")
    assert store.get_run("run-store").status is AgentRunStatus.RUNNING


def test_rt_s05_event_sequence_is_monotonic_under_concurrency(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task_and_run(_task(), _run())

    def append(index: int) -> AgentEvent:
        return store.append_event(
            AgentEvent(
                event_id=f"event-{index}",
                event_type=AgentEventType.TASK_PROGRESS,
                task_id="task-store",
                run_id="run-store",
                trace_id="trace-store",
                elapsed_ms=index,
                payload={"index": index},
            )
        )

    with ThreadPoolExecutor(max_workers=20) as executor:
        persisted = tuple(executor.map(append, range(100)))

    assert sorted(event.sequence for event in persisted) == list(range(100))
    events = store.list_events("run-store")
    assert [event.sequence for event in events] == list(range(100))
    assert len({event.event_id for event in events}) == 100
    assert {event.elapsed_ms for event in events} == set(range(100))


def test_step_tool_call_and_lease_records_round_trip(tmp_path) -> None:
    store = _store(tmp_path)
    store.create_task_and_run(_task(), _run())
    step = AgentStepRecord(task_id="step-1", run_id="run-store")
    call = AgentToolCallRecord(
        tool_call_id="tool-call-1",
        run_id="run-store",
        step_id="step-1",
        tool_name="knowledge_search",
        effect="read",
        arguments_hash="args-hash",
        idempotency_key="idempotency-key",
        timeout_ms=20_000,
    )

    store.save_step(step)
    store.save_tool_call(call)
    claimed = store.claim_run(
        lease_owner="worker-round-trip",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert store.get_step("run-store", "step-1") == step
    assert store.get_tool_call("tool-call-1") == call
    assert claimed is not None
    assert store.get_lease("run-store").lease_owner == "worker-round-trip"
