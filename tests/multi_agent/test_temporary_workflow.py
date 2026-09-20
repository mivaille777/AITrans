from pathlib import Path

from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.api.agent import _state_from_run_request
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext
from backend.models.agent_tools import AgentRunRequest
from backend.services.research_orchestration_service import ResearchOrchestrationService


class Resolver:
    def resolve(self, **_):
        return ScopeContext.issue(
            profile_id="profile-a",
            workspace_id="workspace-a",
            scope_revision="temporary",
        )


class Router:
    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.FAST,
            reason_code="test",
            user_visible_reason="test",
        )


class Planner:
    def plan(self, **_):
        return None


class NeverExecutor:
    def execute(self, **_):
        raise AssertionError("FAST temporary workflow must not execute specialists")


def test_temporary_orchestration_does_not_create_memory_jobs_or_snapshots(tmp_path):
    marker = "TEMPORARY-UNIQUE-MARKER-9f80"
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    service = ResearchOrchestrationService(
        scope_resolver=Resolver(),
        executor=NeverExecutor(),
        temporary_executor=NeverExecutor(),
        router=Router(),
        planner=Planner(),
        memory_port=MemoryCoordinator(repository),
    )
    run = service.run(
        marker,
        profile_id="profile-a",
        run_id="temporary-run",
        runtime_context={"workspace_id": "workspace-a", "temporary": True},
    )

    assert run.memory_snapshot["status"] == "temporary"
    for database in Path(tmp_path).rglob("*.sqlite3"):
        assert marker.encode() not in database.read_bytes()
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_snapshots").fetchone()[0]
            == 0
        )


def test_temporary_runtime_skips_trace_recorders():
    recorded = []

    def workflow(state):
        state.apply_response({"status": "completed", "output_text": "ephemeral"})
        return state

    runtime = AgentRuntime(
        workflow_adapter=workflow,
        run_recorder=lambda *_: recorded.append("run"),
        event_recorder=lambda *_: recorded.append("event"),
    )
    state = AgentState(
        user_input="temporary body",
        browser_context={"temporary": True},
    )
    runtime.execute(state)
    assert recorded == []


def test_temporary_request_reaches_authoritative_runtime_context():
    state = _state_from_run_request(
        AgentRunRequest(
            session_id="temporary-session",
            user_message="temporary request",
            temporary=True,
        )
    )

    assert state.browser_context["temporary"] is True
