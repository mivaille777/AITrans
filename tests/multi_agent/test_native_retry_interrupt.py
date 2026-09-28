from __future__ import annotations

from threading import Barrier, Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from typing import TypedDict

import pytest

from app.ai.errors import (
    AIAuthenticationError,
    AIConnectionError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
)
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentDecisionTimeoutError,
    AgentRuntimeError,
)
from backend.agent_core.orchestration.agent_registry import AgentRegistry, AgentSpec
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import (
    AgentExecutionPolicy,
    AgentRunControl,
    is_transient_provider_error,
    run_node_operation_with_timeout,
)
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.factory import build_root_graph
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_artifacts import (
    ArtifactKind,
    DocumentAnalysisArtifact,
)
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import (
    ScopeContext,
    TaskInputRef,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class State(TypedDict, total=False):
    value: int


class Context(TypedDict, total=False):
    pass


def _retry_graph(route_orchestration):
    names = (
        "resolve_context",
        "prepare_conversation",
        "route_orchestration",
        "resolve_scope",
        "load_memory_snapshot",
        "plan_tasks",
        "validate_plan",
        "block_orchestration",
        "run_collaboration",
        "knowledge_access",
        "knowledge_scope",
        "route_request",
        "execute_direct",
        "start_react",
        "decide_react",
        "execute_react_tool",
        "finalize_react",
        "finalize_conversation",
    )
    nodes = {name: (lambda _state: {}) for name in names}
    nodes["route_orchestration"] = route_orchestration
    graph, _temporary = build_root_graph(
        state_schema=State,
        context_schema=Context,
        nodes=nodes,
        route_branch=lambda _state: "completed",
        orchestration_branch=lambda _state: "fast",
        decision_branch=lambda _state: "final",
        observation_branch=lambda _state: "finalize",
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    return graph


def test_error_taxonomy_retries_only_known_transient_failures():
    assert is_transient_provider_error(AIConnectionError("offline"))
    assert is_transient_provider_error(AITimeoutError("timeout"))
    assert is_transient_provider_error(OSError("socket reset"))
    assert is_transient_provider_error(TimeoutError("read timed out"))
    assert is_transient_provider_error(AIResponseError("server error", status_code=503))
    assert not is_transient_provider_error(AIResponseError("bad request", status_code=400))
    assert not is_transient_provider_error(AIAuthenticationError("unauthorized"))
    assert not is_transient_provider_error(AIRateLimitError("rate limited"))
    assert not is_transient_provider_error(AgentBudgetExceededError("budget"))
    assert not is_transient_provider_error(AgentCancelledError("cancelled"))
    assert not is_transient_provider_error(AgentRuntimeError("scope denied"))


def test_native_root_retries_a_transient_provider_failure_to_success():
    calls = 0

    def route(_state):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AIConnectionError("brief network outage")
        return {}

    graph = _retry_graph(route)
    graph.invoke({})
    assert calls == 2


def test_native_root_does_not_retry_unknown_business_errors():
    calls = 0

    def route(_state):
        nonlocal calls
        calls += 1
        raise AgentRuntimeError("scope changed", stage="scope")

    graph = _retry_graph(route)
    with pytest.raises(AgentRuntimeError, match="scope changed"):
        graph.invoke({})
    assert calls == 1


def test_node_timeout_is_bounded_by_the_remaining_run_budget():
    control = AgentRunControl(
        policy=AgentExecutionPolicy(total_timeout_seconds=10, node_timeout_seconds=8),
        started_at=monotonic() - 9.95,
    )
    assert 0 < control.bounded_node_timeout(8) <= 0.06


def test_safe_provider_node_timeout_is_reported_as_retryable():
    control = AgentRunControl(
        policy=AgentExecutionPolicy(total_timeout_seconds=2, node_timeout_seconds=0.02)
    )
    with pytest.raises(AgentDecisionTimeoutError):
        run_node_operation_with_timeout(
            lambda: sleep(0.1),
            control=control,
            node_timeout_seconds=0.02,
            stage="safe_provider_test",
        )
    assert is_transient_provider_error(AgentDecisionTimeoutError("timed out"))


class _SpecialistState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict
    result: TaskResult


class _NeverLegacyExecutor:
    def __init__(self) -> None:
        from backend.agent_core.orchestration.parallel_executor import (
            ParallelExecutionPolicy,
        )

        self.policy = ParallelExecutionPolicy()

    def execute(self, **_kwargs):
        raise AssertionError("native retry must not use the legacy task executor")


class _Router:
    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            reason_code="native-retry-test",
        )


class _ScopeResolver:
    def __init__(self) -> None:
        self.revision = "scope-v1"

    def resolve(self, *, profile_id="", memory_policy_revision="", **_kwargs):
        return ScopeContext.issue(
            profile_id=profile_id,
            scope_revision=self.revision,
            memory_policy_revision=memory_policy_revision,
            allowed_document_ids=["paper-a"],
        )


class _Memory:
    def __init__(self) -> None:
        self.revision = "memory-policy-v1"
        self.candidate_submissions: list[dict] = []

    def policy_revision(self, _profile_id):
        return self.revision

    def load_snapshot(self, *, profile_id, scope, **_kwargs):
        return {
            "status": "ready",
            "snapshot_id": "retry-memory-snapshot",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
            "policy_revision": scope.memory_policy_revision,
            "role_projections": {},
        }

    def submit_candidates(self, **kwargs):
        self.candidate_submissions.append(kwargs)


class _ProductService:
    def resolve_route(self, **_payload):
        return (
            AgentRouteDecision(kind="answer", source="deterministic", intent="answer"),
            {"duration_ms": 0, "llm_called": False},
        )

    def run(self, **payload):
        return SimpleNamespace(
            status="completed",
            plan={"action": "answer", "user_visible_reason": "test"},
            output_text="done",
            provider="test",
            model="test",
            request_id=0,
            tool_result=None,
            route=AgentRouteDecision.model_validate(payload["_resolved_route"]),
        )


def _retry_fixture(tmp_path, task_runner=None):
    artifact_store = InMemoryArtifactStore()
    calls: list[str] = []
    b_attempts = 0

    def default_task_runner(task: TaskSpec, _runtime, artifact_store):
        nonlocal b_attempts
        calls.append(task.task_id)
        if task.task_id == "b":
            b_attempts += 1
            if b_attempts == 1:
                return TaskResult(
                    task_id=task.task_id,
                    attempt_id=f"{task.task_id}:1",
                    attempt_ordinal=1,
                    status=TaskStatus.FAILED,
                    error_code="transient_test_failure",
                )
        artifact = artifact_store.put(
            DocumentAnalysisArtifact(
                artifact_id=f"artifact:{task.task_id}",
                producer_task_id=task.task_id,
                scope_ref=task.scope_ref,
                document_id="paper-a",
            )
        )
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            attempt_ordinal=1,
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[artifact.ref()],
        )

    active_task_runner = task_runner or default_task_runner

    agent_ids = ("retry-agent-a", "retry-agent-b", "retry-agent-c", "retry-agent-d")

    def build_specialist(agent_id):
        from langgraph.graph import END, START, StateGraph

        def work(state: _SpecialistState, runtime):
            return {
                "result": active_task_runner(
                    TaskSpec.model_validate(state["task"]), runtime, artifact_store
                )
            }

        builder = StateGraph(_SpecialistState)
        builder.add_node("work", work)
        builder.add_edge(START, "work")
        builder.add_edge("work", END)
        return builder.compile()

    specs = tuple(
        AgentSpec(
            agent_id=agent_id,
            version="test-v1",
            display_name=agent_id,
            description="Stage 9 retry fixture",
            capabilities=frozenset({"test"}),
            accepted_input_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
            output_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
            allowed_tools=frozenset(),
            default_tools=(),
            default_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
            graph_factory=lambda agent_id=agent_id: build_specialist(agent_id),
        )
        for agent_id in agent_ids
    )
    registry = AgentRegistry(specs)
    task_specs = (
        ("a", agent_ids[0], ()),
        ("b", agent_ids[1], ("a",)),
        ("c", agent_ids[2], ()),
        ("d", agent_ids[3], ("b",)),
    )

    def planner_provider(*, scope_ref, plan_revision, **_kwargs):
        tasks = []
        for task_id, agent_id, dependencies in task_specs:
            tasks.append(
                TaskSpec(
                    task_id=task_id,
                    agent_id=agent_id,
                    objective=f"run {task_id}",
                    depends_on=list(dependencies),
                    input_refs=[
                        TaskInputRef(
                            artifact_id=f"artifact:{dependency}",
                            version=1,
                            kind=ArtifactKind.DOCUMENT_ANALYSIS,
                            producer_task_id=dependency,
                        )
                        for dependency in dependencies
                    ],
                    required=True,
                    expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
                    scope_ref=scope_ref,
                    allowed_tools=[],
                    plan_revision=plan_revision,
                )
            )
        return {
            "plan_id": f"retry-plan-{plan_revision}",
            "plan_revision": plan_revision,
            "scope_ref": scope_ref,
            "tasks": [item.model_dump(mode="json") for item in tasks],
        }

    scope_resolver = _ScopeResolver()
    memory = _Memory()
    executor = _NeverLegacyExecutor()
    service = ResearchOrchestrationService(
        scope_resolver=scope_resolver,
        executor=executor,
        router=_Router(),
        planner=ValidatedSupervisorPlanner(
            agent_registry=registry,
            provider=planner_provider,
        ),
        memory_port=memory,
        artifact_store=artifact_store,
    )
    bridge = MultiAgentRuntimeBridge(orchestrator=service)
    checkpoint_service = AgentCheckpointService(
        storage_path=tmp_path / "retry-checkpoints.sqlite3"
    )
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(_ProductService()),
        checkpointer=checkpoint_service.checkpointer,
        orchestration_service=service,
        collaboration_adapter=bridge,
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    state = AgentState(
        task_id="task-native-retry",
        run_id="run-native-retry",
        trace_id="trace-native-retry",
        user_input="Run the retry workflow",
        browser_context={
            "profile_id": "profile-native-retry",
            "knowledge_document_ids": ["paper-a"],
            "multi_agent_mode": "force",
        },
    )
    return graph, checkpoint_service, state, calls, artifact_store, scope_resolver, memory


def test_native_manual_retry_preserves_successful_siblings_and_increments_attempts(
    tmp_path,
):
    graph, checkpoints, state, calls, _artifacts, _scope, _memory = _retry_fixture(
        tmp_path
    )
    initial = graph.run_with_events(state, lambda *_args: None)
    assert calls.count("a") == 1
    assert calls.count("c") == 1
    assert "d" not in calls

    reopened = graph.prepare_task_retry(initial, "b")
    assert reopened == ("b", "d")
    retried = graph.resume_with_events(initial, lambda *_args: None)
    latest = {
        result["task_id"]: TaskResult.model_validate(result)
        for result in retried.orchestration_results
    }
    assert calls.count("a") == 1
    assert calls.count("c") == 1
    assert calls.count("b") == 2
    assert calls.count("d") == 1
    assert latest["a"].attempt_id == "a:1"
    assert latest["c"].attempt_id == "c:1"
    assert latest["b"].attempt_id == "b:2"
    assert latest["d"].attempt_id == "d:2"
    assert all(item.status is TaskStatus.SUCCEEDED for item in latest.values())
    checkpoints.close()


def test_native_manual_retry_revalidates_scope_memory_and_retained_artifacts(tmp_path):
    graph, checkpoints, state, _calls, artifacts, scope, memory = _retry_fixture(
        tmp_path
    )
    initial = graph.run_with_events(state, lambda *_args: None)

    scope.revision = "scope-revoked-v2"
    with pytest.raises(AgentRuntimeError) as scope_error:
        graph.prepare_task_retry(initial, "b")
    assert scope_error.value.fallback_reason == "prepared_scope_changed"
    scope.revision = "scope-v1"

    memory.revision = "memory-policy-v2"
    with pytest.raises(AgentRuntimeError) as memory_error:
        graph.prepare_task_retry(initial, "b")
    assert memory_error.value.fallback_reason == "prepared_scope_changed"
    memory.revision = "memory-policy-v1"

    assert artifacts.revoke("artifact:c", 1, reason="source revoked")
    with pytest.raises(AgentRuntimeError) as artifact_error:
        graph.prepare_task_retry(initial, "b")
    assert artifact_error.value.fallback_reason == "retry_artifact_invalid"
    checkpoints.close()


def test_native_cancel_fences_late_artifacts_and_memory_candidates(tmp_path):
    entered = Barrier(3)
    release = Event()
    control = AgentRunControl()
    errors: list[BaseException] = []
    event_types: list[str] = []

    def delayed_task(task, runtime, artifact_store):
        entered.wait(timeout=5)
        assert release.wait(5)
        artifact = DocumentAnalysisArtifact(
            artifact_id=f"artifact:{task.task_id}",
            producer_task_id=task.task_id,
            scope_ref=task.scope_ref,
            document_id="paper-a",
        )
        from backend.agent_core.orchestration.specialist_adapter import (
            commit_specialist_effect,
        )

        stored = commit_specialist_effect(
            runtime,
            f"artifact_commit:{task.task_id}",
            lambda: artifact_store.put(artifact),
        )
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[stored.ref()],
        )

    graph, checkpoints, state, _calls, artifacts, _scope, memory = _retry_fixture(
        tmp_path, task_runner=delayed_task
    )

    def run_graph():
        try:
            graph.run_with_events(
                state,
                lambda event_type, _payload: event_types.append(
                    str(getattr(event_type, "value", event_type))
                ),
                control=control,
            )
        except BaseException as exc:  # noqa: BLE001 - collect worker-thread outcome
            errors.append(exc)

    worker = Thread(target=run_graph)
    worker.start()
    entered.wait(timeout=8)
    control.cancel()
    release.set()
    worker.join(timeout=8)

    assert not worker.is_alive()
    assert errors and isinstance(errors[0], AgentCancelledError)
    assert artifacts.get("artifact:a", 1) is None
    assert artifacts.get("artifact:c", 1) is None
    assert not memory.candidate_submissions
    assert "task_completed" not in event_types
    assert "multi_agent_completed" not in event_types
    assert state.response_state.status != "completed"
    checkpoints.close()
