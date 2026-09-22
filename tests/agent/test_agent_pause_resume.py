from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.agent_core.exceptions import AgentPauseRequestedError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.api.agent_runtime_jobs import get_agent_run_store
from backend.main import create_app
from backend.models.agent_run import AgentRunStatus
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan, AgentToolExecuteResponse
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore, AgentRunStoreConflictError
from backend.services.agent_run_worker import AgentRunWorker


class RouteProbe:
    def __init__(self, *, pause_after_route: bool = False) -> None:
        self.pause_after_route = pause_after_route
        self.routes = 0
        self.executions = 0

    def resolve_route(self, *, control, **_payload):
        self.routes += 1
        if self.pause_after_route:
            control.pause()
        return (
            AgentRouteDecision(
                kind="answer", source="deterministic", intent="answer"
            ),
            {"llm_called": False},
        )

    def run(self, *, _resolved_route=None, **_payload):
        self.executions += 1
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="answer", user_visible_reason="done"),
            output_text="done",
            provider="fake",
            model="fake",
            request_id=0,
            tool_result=None,
            route=AgentRouteDecision.model_validate(_resolved_route),
        )


class RetrievalProbe(RouteProbe):
    def resolve_route(self, **_payload):
        self.routes += 1
        return (
            AgentRouteDecision(
                kind="tool",
                source="deterministic",
                intent="search_knowledge_base",
                tool_name="search_knowledge_base",
            ),
            {"llm_called": False},
        )

    def run(self, *, control, _resolved_route=None, **_payload):
        self.executions += 1
        if self.pause_after_route:
            control.pause()
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool", tool_name="search_knowledge_base", user_visible_reason="found"
            ),
            output_text="retrieved",
            provider="fake",
            model="fake",
            request_id=0,
            tool_result=AgentToolExecuteResponse(
                tool_name="search_knowledge_base",
                output_text="evidence",
                effect="read",
            ),
            route=AgentRouteDecision.model_validate(_resolved_route),
        )


def _runtime(service: RouteProbe, checkpoint_path) -> tuple[AgentRuntime, AgentCheckpointService]:
    checkpoint = AgentCheckpointService(storage_path=checkpoint_path)
    runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service), checkpointer=checkpoint.checkpointer
        )
    )
    return runtime, checkpoint


def test_cp_r01_pause_after_route_resumes_without_repeating_route(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite3"
    first_service = RouteProbe(pause_after_route=True)
    first, checkpoint = _runtime(first_service, path)
    state = AgentState(run_id="run-paused-route", task_id="task-paused-route")

    with pytest.raises(AgentPauseRequestedError):
        first.execute(state, control=AgentRunControl())
    assert first_service.routes == 1
    assert first_service.executions == 0
    metadata = first.checkpoint_metadata(state.run_id)
    assert metadata is not None and metadata["checkpoint_id"]
    checkpoint.close()

    resumed_service = RouteProbe()
    second, reopened = _runtime(resumed_service, path)
    restored = second.restore_checkpoint(state.run_id)
    result = second.execute(restored, resume=True)
    assert result.response["output_text"] == "done"
    assert resumed_service.routes == 0
    assert resumed_service.executions == 1
    reopened.close()


def test_cp_r02_pause_after_retrieval_does_not_repeat_read_tool(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite3"
    first_service = RetrievalProbe(pause_after_route=True)
    first, checkpoint = _runtime(first_service, path)
    run_id = "run-paused-retrieval"
    with pytest.raises(AgentPauseRequestedError):
        first.execute(AgentState(run_id=run_id, task_id="task-retrieval"))
    assert first_service.executions == 1
    checkpoint.close()

    resumed_service = RetrievalProbe()
    second, reopened = _runtime(resumed_service, path)
    result = second.execute(second.restore_checkpoint(run_id), resume=True)
    assert result.response["output_text"] == "retrieved"
    assert resumed_service.routes == 0
    assert resumed_service.executions == 0
    reopened.close()


@pytest.mark.asyncio
async def test_pause_and_resume_lifecycle_uses_checkpoint_boundary(tmp_path) -> None:
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    run = AgentRunScheduler(store).enqueue(goal="Pause safely")
    started = asyncio.Event()
    calls = []

    async def execute(current, control, recovering):
        calls.append((recovering, control.policy.total_timeout_seconds))
        if not recovering:
            started.set()
            while not control.pause_event.is_set():
                await asyncio.sleep(0.005)
            control.pause_at_boundary("next_node")
        return AgentRunStatus.COMPLETED

    worker = AgentRunWorker(
        store, execute, heartbeat_seconds=0.01, lease_seconds=0.2
    )
    task = asyncio.create_task(worker.run_once())
    await started.wait()
    assert AgentRunScheduler(store).pause(run.run_id).status is AgentRunStatus.PAUSE_REQUESTED
    paused = await asyncio.wait_for(task, timeout=2)
    assert paused.status is AgentRunStatus.PAUSED
    assert paused.finished_at is None
    assert store.get_lease(run.run_id) is None
    assert AgentRunScheduler(store).resume(run.run_id).status is AgentRunStatus.RECOVERING
    completed = await worker.run_once()
    assert completed.status is AgentRunStatus.COMPLETED
    assert calls[0] == (False, 45)
    assert calls[1][0] is True
    assert 0 < calls[1][1] < 45
    assert completed.budget_used_ms >= paused.budget_used_ms > 0
    with pytest.raises(AgentRunStoreConflictError):
        AgentRunScheduler(store).resume(run.run_id)


def test_pause_resume_http_contract_rejects_invalid_states(tmp_path) -> None:
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    run = AgentRunScheduler(store).enqueue(goal="Pause from API")
    app = create_app()
    app.dependency_overrides[get_agent_run_store] = lambda: store
    client = TestClient(app)
    assert client.post(f"/api/agent/runtime/runs/{run.run_id}/pause").status_code == 409
    store.claim_run(lease_owner="api-test")
    assert client.post(f"/api/agent/runtime/runs/{run.run_id}/pause").json()["status"] == "pause_requested"
    store.finish_owned_run(
        run.run_id, lease_owner="api-test", target_status=AgentRunStatus.PAUSED
    )
    assert client.post(f"/api/agent/runtime/runs/{run.run_id}/resume").json()["status"] == "recovering"
    assert client.post(f"/api/agent/runtime/runs/{run.run_id}/resume").status_code == 409
    assert client.post("/api/agent/runtime/runs/missing/pause").status_code == 404
