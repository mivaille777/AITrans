from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from functools import partial
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.api.agent_runtime_jobs import (
    execute_persisted_agent_run,
    get_agent_run_store,
)
from backend.main import create_app
from backend.models.agent_run import AgentRunStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.services.agent_run_scheduler import PROFILE_BUDGETS, AgentRunScheduler
from backend.services.agent_run_store import (
    AGENT_RUNTIME_SCHEMA_VERSION,
    AgentRunStore,
    AgentRunStoreConflictError,
)
from backend.services.agent_run_worker import AgentRunWorker


def _store(tmp_path) -> AgentRunStore:
    return AgentRunStore(storage_path=tmp_path / "agent_runtime.sqlite3")


@pytest.mark.asyncio
async def test_rt_w01_queued_run_is_executed_by_worker(tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(goal="Analyze the paper")
    calls = []

    async def execute(run, control, recovering):
        calls.append((run.run_id, control.policy.total_timeout_seconds, recovering))

    worker = AgentRunWorker(store, execute)
    result = await worker.run_once()

    assert result.status is AgentRunStatus.COMPLETED
    assert calls == [(queued.run_id, 45, False)]
    assert store.get_lease(queued.run_id) is None
    assert await worker.run_once() is None


@pytest.mark.asyncio
async def test_rt_w02_two_workers_never_execute_same_run(tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(goal="One run")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def execute(run, control, recovering):
        calls.append(run.run_id)
        started.set()
        await release.wait()

    first = AgentRunWorker(store, execute, worker_id="first")
    second = AgentRunWorker(store, execute, worker_id="second")
    first_task = asyncio.create_task(first.run_once())
    await started.wait()
    assert await second.run_once() is None
    release.set()
    await first_task
    assert calls == [queued.run_id]


@pytest.mark.asyncio
async def test_rt_w03_w04_expired_lease_can_be_reclaimed(tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(
        goal="Resume a long task", runtime_profile=AgentRuntimeProfile.LONG_TASK
    )
    old = datetime(2026, 1, 1, tzinfo=UTC)
    store.claim_run(lease_owner="crashed", lease_seconds=3, now=old)
    assert store.recover_expired_runs(now=old + timedelta(seconds=2)) == ()
    assert store.recover_expired_runs(now=old + timedelta(seconds=3)) == (queued.run_id,)
    assert store.get_run(queued.run_id).status is AgentRunStatus.RECOVERING
    assert store.get_lease(queued.run_id) is None

    resumes = []

    async def execute(run, control, recovering):
        resumes.append((recovering, control.policy.total_timeout_seconds))

    result = await AgentRunWorker(store, execute, worker_id="replacement").run_once()
    assert result.status is AgentRunStatus.COMPLETED
    assert resumes == [(True, 1800)]
    with pytest.raises(AgentRunStoreConflictError):
        store.finish_owned_run(
            queued.run_id,
            lease_owner="crashed",
            target_status=AgentRunStatus.FAILED,
        )


@pytest.mark.asyncio
async def test_rt_w05_cancel_stops_worker_and_fences_completion(tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(goal="Cancel me")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def execute(run, control, recovering):
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    worker = AgentRunWorker(
        store, execute, heartbeat_seconds=0.01, lease_seconds=0.2
    )
    task = asyncio.create_task(worker.run_once())
    await started.wait()
    AgentRunScheduler(store).cancel(queued.run_id)
    result = await asyncio.wait_for(task, timeout=2)
    assert result.status is AgentRunStatus.CANCELLED
    assert cancelled.is_set()
    assert store.get_lease(queued.run_id) is None


def test_rt_w06_profiles_have_distinct_bounded_budgets() -> None:
    interactive = PROFILE_BUDGETS[AgentRuntimeProfile.INTERACTIVE]
    long_task = PROFILE_BUDGETS[AgentRuntimeProfile.LONG_TASK]
    assert (interactive.policy.total_timeout_seconds, interactive.policy.tool_timeout_seconds) == (45, 20)
    assert (interactive.policy.max_plan_steps, interactive.policy.max_tool_calls) == (4, 4)
    assert (long_task.policy.total_timeout_seconds, long_task.policy.tool_timeout_seconds) == (1800, 120)
    assert (long_task.policy.max_plan_steps, long_task.policy.max_tool_calls) == (20, 40)
    assert long_task.max_parallel_tools == 4


def test_heartbeat_rejects_stale_or_wrong_owner_and_terminal_run(tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(goal="Lease")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    store.claim_run(lease_owner="owner", lease_seconds=4, now=base)
    assert not store.heartbeat_lease(queued.run_id, lease_owner="other", now=base)
    assert store.heartbeat_lease(
        queued.run_id,
        lease_owner="owner",
        lease_seconds=4,
        now=base + timedelta(seconds=3),
    )
    assert not store.heartbeat_lease(
        queued.run_id, lease_owner="owner", now=base + timedelta(seconds=8)
    )
    store.recover_expired_runs(now=base + timedelta(seconds=8))
    assert not store.heartbeat_lease(
        queued.run_id, lease_owner="owner", now=base + timedelta(seconds=8)
    )


def test_runtime_jobs_api_enqueues_durable_request_and_supports_cancel(tmp_path) -> None:
    store = _store(tmp_path)
    app = create_app()
    app.dependency_overrides[get_agent_run_store] = lambda: store
    client = TestClient(app)
    response = client.post(
        "/api/agent/runtime/tasks",
        json={
            "request": {"user_message": "Summarize this paper", "context_mode": "general"},
            "runtime_profile": "long_task",
        },
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert response.json()["status"] == "queued"
    assert store.get_run_request(run_id)["user_message"] == "Summarize this paper"
    assert client.get(f"/api/agent/runtime/runs/{run_id}").json()["status"] == "queued"
    assert client.get(f"/api/agent/runtime/runs/{run_id}/events").json() == []
    assert client.get(f"/api/agent/runtime/runs/{run_id}/result").json() == {
        "status": "queued",
        "result": None,
    }
    assert client.post(f"/api/agent/runtime/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.get("/api/agent/runtime/runs/missing").status_code == 404
    assert client.post(
        "/api/agent/runtime/tasks",
        json={
            "request": {
                "user_message": "Do not queue approval",
                "confirmed_write_tools": ["save_research_note"],
            }
        },
    ).status_code == 400


def test_run_request_survives_reopened_store_and_events_are_fenced(tmp_path) -> None:
    path = tmp_path / "agent_runtime.sqlite3"
    store = AgentRunStore(storage_path=path)
    run = AgentRunScheduler(store).enqueue(
        goal="Persist request", request_payload={"user_message": "Persist request"}
    )
    store.close()
    reopened = AgentRunStore(storage_path=path)
    assert reopened.get_run_request(run.run_id) == {"user_message": "Persist request"}
    base = datetime(2026, 1, 1, tzinfo=UTC)
    reopened.claim_run(lease_owner="owner", now=base, lease_seconds=5)
    event = AgentEvent(
        event_type=AgentEventType.TASK_PROGRESS,
        task_id=run.task_id,
        run_id=run.run_id,
        trace_id=run.trace_id,
    )
    with pytest.raises(AgentRunStoreConflictError):
        reopened.append_event(event, lease_owner="other", now=base)
    reopened.append_event(event, lease_owner="owner", now=base)
    reopened.recover_expired_runs(now=base + timedelta(seconds=5))
    with pytest.raises(AgentRunStoreConflictError):
        reopened.append_event(
            AgentEvent(
                event_type=AgentEventType.TASK_PROGRESS,
                task_id=run.task_id,
                run_id=run.run_id,
                trace_id=run.trace_id,
            ),
            lease_owner="owner",
            now=base + timedelta(seconds=5),
        )
    assert len(reopened.list_events(run.run_id)) == 1


@pytest.mark.asyncio
async def test_worker_executes_persisted_request_outside_http(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    queued = AgentRunScheduler(store).enqueue(
        goal="Analyze later",
        request_payload={"user_message": "Analyze later", "context_mode": "general"},
    )
    received = []

    class Runtime:
        def checkpoint_metadata(self, run_id):
            return {
                "graph_version": "reading-agent-ma03-v1",
                "state_schema_version": 2,
                "checkpoint_id": "checkpoint-test",
            }

        def execute(self, state, *, control, resume, event_sink):
            received.append((state.task_id, state.run_id, state.user_input, resume))
            control.checkpoint("test_runtime")
            event_sink(
                AgentEvent(
                    event_type=AgentEventType.AGENT_START,
                    task_id=state.task_id,
                    run_id=state.run_id,
                    trace_id=state.trace_id,
                )
            )
            state.response = {"status": "completed", "output_text": "done"}
            return state

    monkeypatch.setattr("backend.api.agent_runtime_jobs._build_runtime", Runtime)
    monkeypatch.setattr(
        "backend.api.agent_runtime_jobs.get_research_workspace_service", lambda: None
    )
    monkeypatch.setattr(
        "backend.api.agent_runtime_jobs.get_research_note_service", lambda: None
    )
    worker = AgentRunWorker(
        store,
        partial(execute_persisted_agent_run, store=store, lease_owner="test-worker"),
        worker_id="test-worker",
    )
    result = await worker.run_once()
    assert result.status is AgentRunStatus.COMPLETED
    assert received == [(queued.task_id, queued.run_id, "Analyze later", False)]
    assert [event.event_type for event in store.list_events(queued.run_id)] == [
        AgentEventType.AGENT_START
    ]
    assert store.get_run_result(queued.run_id)["output_text"] == "done"
    persisted = store.get_run(queued.run_id)
    assert persisted.graph_version == "reading-agent-ma03-v1"
    assert persisted.state_schema_version == 2
    assert persisted.checkpoint_id == "checkpoint-test"


def test_app_lifespan_starts_background_worker(monkeypatch, tmp_path) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr("backend.main.get_agent_run_store", lambda: store)
    monkeypatch.setattr("backend.main.close_agent_run_store", lambda: None)

    async def fake_execute(run, control, recovering, *, store, lease_owner):
        assert store.get_run_request(run.run_id)["user_message"] == "Queued from HTTP"
        return AgentRunStatus.COMPLETED

    monkeypatch.setattr("backend.main.execute_persisted_agent_run", fake_execute)
    app = create_app()
    app.dependency_overrides[get_agent_run_store] = lambda: store
    with TestClient(app) as client:
        response = client.post(
            "/api/agent/runtime/tasks",
            json={"request": {"user_message": "Queued from HTTP"}},
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        deadline = monotonic() + 3
        while monotonic() < deadline:
            if client.get(f"/api/agent/runtime/runs/{run_id}").json()["status"] == "completed":
                break
            sleep(0.02)
        assert store.get_run(run_id).status is AgentRunStatus.COMPLETED


def test_stage2_database_schema_upgrades_without_losing_runs(tmp_path) -> None:
    path = tmp_path / "agent_runtime.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE agent_tasks (
                task_id TEXT PRIMARY KEY, goal TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                trace_id TEXT NOT NULL, runtime_profile TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO agent_tasks VALUES ('old-task', 'Existing work', '', '2026-01-01')"
        )
        connection.execute(
            """
            INSERT INTO agent_runs VALUES (
                'old-run', 'old-task', 'old-trace', 'interactive',
                'queued', '2026-01-01', '2026-01-01', NULL, NULL
            )
            """
        )
    upgraded = AgentRunStore(storage_path=path)
    assert upgraded.get_run("old-run").status is AgentRunStatus.QUEUED
    assert upgraded.get_run_request("old-run") == {}
    assert upgraded.get_run_result("old-run") is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM agent_runtime_state WHERE key = 'schema_version'"
        ).fetchone()[0] == str(AGENT_RUNTIME_SCHEMA_VERSION)
        assert "result_json" in {
            row[1] for row in connection.execute("PRAGMA table_info(agent_tool_calls)")
        }
