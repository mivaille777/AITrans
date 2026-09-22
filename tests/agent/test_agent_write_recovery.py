from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from backend.api.agent_runtime_jobs import execute_persisted_agent_run
from backend.models.agent_run import (
    AgentRunStatus,
    AgentStepRecord,
    AgentToolCallRecord,
    AgentToolCallStatus,
)
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore, AgentRunStoreConflictError
from backend.services.agent_run_worker import AgentRunWorker


def _running_call(run_id: str, *, effect: str, call_id: str) -> AgentToolCallRecord:
    return AgentToolCallRecord(
        tool_call_id=call_id,
        run_id=run_id,
        step_id="step-1",
        tool_name=f"{effect}_tool",
        effect=effect,
        arguments_hash="hash",
        idempotency_key=f"key-{call_id}",
        status=AgentToolCallStatus.RUNNING,
        timeout_ms=20_000,
    )


@pytest.mark.asyncio
async def test_cp_w01_w02_uncertain_write_is_fenced_and_never_replayed(
    monkeypatch, tmp_path
) -> None:
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    run = AgentRunScheduler(store).enqueue(
        goal="Write once", request_payload={"user_message": "Write once"}
    )
    old = datetime(2026, 1, 1, tzinfo=UTC)
    store.save_step(AgentStepRecord(task_id="step-1", run_id=run.run_id))
    store.save_tool_call(_running_call(run.run_id, effect="write", call_id="write-1"))
    store.claim_run(lease_owner="crashed", now=old, lease_seconds=2)
    # The external write succeeded, but the process died before recording its
    # result. The replacement must not execute it a second time.
    write_count = 1
    store.recover_expired_runs(now=old + timedelta(seconds=2))

    def forbidden_runtime():
        raise AssertionError("blocked write must not enter the graph")

    monkeypatch.setattr("backend.api.agent_runtime_jobs._build_runtime", forbidden_runtime)
    worker = AgentRunWorker(
        store,
        partial(execute_persisted_agent_run, store=store, lease_owner="replacement"),
        worker_id="replacement",
    )
    result = await worker.run_once()
    assert result.status is AgentRunStatus.WAITING
    assert write_count == 1
    assert store.get_tool_call("write-1").status is AgentToolCallStatus.BLOCKED_RECOVERY
    assert store.get_run_result(run.run_id)["code"] == "write_recovery_blocked"


def test_cp_w03_read_call_can_be_retried_after_reclaim(tmp_path) -> None:
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    run = AgentRunScheduler(store).enqueue(goal="Read again")
    old = datetime(2026, 1, 1, tzinfo=UTC)
    store.save_step(AgentStepRecord(task_id="step-1", run_id=run.run_id))
    store.save_tool_call(_running_call(run.run_id, effect="read", call_id="read-1"))
    store.claim_run(lease_owner="old", now=old, lease_seconds=2)
    store.recover_expired_runs(now=old + timedelta(seconds=2))
    store.claim_run(lease_owner="new")

    assert store.prepare_recovery_tool_calls(run.run_id, lease_owner="new") == ()
    assert store.get_tool_call("read-1").status is AgentToolCallStatus.PENDING
    with pytest.raises(AgentRunStoreConflictError):
        store.prepare_recovery_tool_calls(run.run_id, lease_owner="old")
