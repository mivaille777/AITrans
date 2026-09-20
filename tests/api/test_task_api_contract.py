from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent_core.orchestration.parallel_executor import (
    ParallelTaskGraphExecutor,
    SQLiteTaskCheckpointStore,
)
from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.agent_core.state import AgentState
from backend.api.agent_dependencies import get_agent_runtime
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.main import create_app
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_tasks import (
    ScopeContext,
    TaskResult,
    TaskRole,
    TaskSpec,
    TaskStatus,
    ValidatedTaskPlan,
)
from backend.services.agent_trace_store_service import StoredAgentEvent, StoredAgentRun


def _state() -> AgentState:
    scope = ScopeContext.issue(
        profile_id="local-default",
        workspace_id="workspace-1",
        scope_revision="revision-1",
        allowed_document_ids=["paper-a", "paper-b"],
    )
    plan = ValidatedTaskPlan(
        plan_id="plan-1",
        scope_ref=scope.scope_ref,
        tasks=[
            TaskSpec(
                task_id="research-1",
                role=TaskRole.RESEARCH,
                objective="Compare the scoped papers",
                required=True,
                expected_output_kind=ArtifactKind.COMPARISON,
                scope_ref=scope.scope_ref,
            )
        ],
    )
    result = TaskResult(
        task_id="research-1",
        attempt_id="research-1:1",
        status=TaskStatus.FAILED,
        error_code="provider_failed",
    )
    state = AgentState(
        run_id="run-task-api",
        trace_id="trace-task-api",
        session_id="session-1",
        user_input="compare",
        browser_context={"confirmed_write_tools": ["save_research_note"]},
    )
    state.apply_orchestration(
        lane="workflow",
        status="partial",
        scope=scope.model_dump(mode="json"),
        plan=plan.model_dump(mode="json"),
        results=[result.model_dump(mode="json")],
    )
    return state


class SnapshotRuntime:
    def __init__(self) -> None:
        self.state = _state()

    def restore_checkpoint(self, run_id: str) -> AgentState:
        assert run_id == self.state.run_id
        return self.state.model_copy(deep=True)


class TraceStore:
    def get_run(self, run_id: str) -> StoredAgentRun:
        return StoredAgentRun(
            run_id=run_id,
            trace_id="trace-task-api",
            session_id="session-1",
            created_at="2026-09-17T00:00:00Z",
            status="failed",
            intent="complex",
            ui_mode="assistant",
            tool_name="",
            provider="",
            model="",
            total_duration_ms=10,
            planning_duration_ms=0,
            tool_duration_ms=0,
            synthesis_duration_ms=0,
            retry_count=0,
            failure_count=1,
            timeout_count=0,
            fallback_reason="",
            event_count=1,
        )

    def list_events(self, run_id: str) -> tuple[StoredAgentEvent, ...]:
        return (
            StoredAgentEvent(
                sequence=7,
                event_type="task_failed",
                timestamp="2026-09-17T00:00:00Z",
                elapsed_ms=10,
                payload={"task_id": "research-1", "role": "research", "status": "failed"},
            ),
        )


def test_run_snapshot_is_authoritative_and_exposes_retryable_tasks() -> None:
    app = create_app()
    app.dependency_overrides[get_agent_runtime] = SnapshotRuntime
    app.dependency_overrides[get_agent_trace_store_service] = TraceStore
    with TestClient(app) as client:
        response = client.get("/api/agent/runs/run-task-api/snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["plan"]["tasks"][0]["depends_on"] == []
    assert payload["retryable_task_ids"] == ["research-1"]
    assert payload["events"][0]["sequence"] == 7


def test_structured_workflow_action_routes_without_prompt_keyword_guessing() -> None:
    route = ResearchTaskRouter().route(
        "do the selected operation",
        {"workflow_action": "compare_papers", "knowledge_document_ids": ["a", "b"]},
    )
    assert route.lane.value == "workflow"
    assert route.primary_role is TaskRole.RESEARCH
    assert route.reason_code == "explicit_compare_papers"


def test_structured_workflow_action_reports_missing_resource_scope() -> None:
    route = ResearchTaskRouter().route(
        "do it",
        {"workflow_action": "quick_read", "knowledge_document_ids": []},
    )
    assert route.primary_role is TaskRole.DOCUMENT
    assert route.missing_information == ["source_required"]


def test_task_retry_reopens_only_the_failed_task_and_its_descendants(tmp_path) -> None:
    scope = ScopeContext.issue(scope_revision="revision-1")
    document = TaskSpec(
        task_id="document-1",
        role=TaskRole.DOCUMENT,
        objective="Read",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope.scope_ref,
    )
    research = TaskSpec(
        task_id="research-1",
        role=TaskRole.RESEARCH,
        objective="Compare",
        depends_on=[document.task_id],
        required=True,
        expected_output_kind=ArtifactKind.COMPARISON,
        scope_ref=scope.scope_ref,
    )
    writer = TaskSpec(
        task_id="writer-1",
        role=TaskRole.WRITER,
        objective="Draft",
        depends_on=[research.task_id],
        required=True,
        expected_output_kind=ArtifactKind.MANUSCRIPT_SECTION,
        scope_ref=scope.scope_ref,
    )
    plan = ValidatedTaskPlan(
        plan_id="plan-retry",
        scope_ref=scope.scope_ref,
        tasks=[document, research, writer],
    )
    store = SQLiteTaskCheckpointStore(tmp_path / "checkpoint.sqlite3")
    executor = ParallelTaskGraphExecutor({}, checkpoint_store=store)
    plan_hash = executor._plan_hash(plan)
    assert store.acquire_lease(
        run_id="run-retry",
        plan_hash=plan_hash,
        owner_id="setup",
        lease_seconds=30,
    )
    for task, status_value in (
        (document, TaskStatus.SUCCEEDED),
        (research, TaskStatus.FAILED),
        (writer, TaskStatus.BLOCKED),
    ):
        store.begin_task(
            run_id="run-retry",
            task_id=task.task_id,
            plan_hash=plan_hash,
            attempt_ordinal=1,
        )
        store.complete_task(
            run_id="run-retry",
            plan_hash=plan_hash,
            execution=SpecialistExecution(
                result=TaskResult(
                    task_id=task.task_id,
                    attempt_id=f"{task.task_id}:1",
                    status=status_value,
                    error_code="provider_failed" if status_value is TaskStatus.FAILED else "",
                )
            ),
        )
    store.release_lease("run-retry", "setup")

    assert executor.prepare_retry(
        run_id="run-retry", plan=plan, task_id="research-1"
    ) == ("research-1", "writer-1")
    completed, interrupted = store.load("run-retry", plan_hash)
    assert set(completed) == {"document-1"}
    assert interrupted == {"research-1", "writer-1"}
