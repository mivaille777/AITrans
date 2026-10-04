from __future__ import annotations

from threading import Barrier, Lock
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.agent_registry import AgentRegistry, AgentSpec
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.orchestration.parallel_executor import ParallelExecutionPolicy
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_artifacts import Artifact, ArtifactKind, VerificationStatus
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import (
    ScopeContext,
    TaskInputRef,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from backend.models.agent_tools import AgentPlan
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class _SpecialistState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    result: TaskResult


class _NeverExecutor:
    policy = ParallelExecutionPolicy()

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **_kwargs):
        self.calls += 1
        raise AssertionError("native Root must not call the legacy executor")


class _Router:
    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            reason_code="native-send-test",
        )


class _ScopeResolver:
    def resolve(self, *, profile_id="", memory_policy_revision="", **_kwargs):
        return ScopeContext.issue(
            profile_id=profile_id,
            scope_revision="send-test-v1",
            memory_policy_revision=memory_policy_revision,
            allowed_document_ids=["paper-a"],
        )


class _Memory:
    def policy_revision(self, _profile_id):
        return "memory-policy:send-test-v1"

    def load_snapshot(self, *, profile_id, scope, **_kwargs):
        return {
            "status": "ready",
            "snapshot_id": "memory-send-test",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
            "policy_revision": scope.memory_policy_revision,
            "role_projections": {},
        }

    def submit_candidates(self, **_kwargs):
        return None


class _ProductService:
    def resolve_route(self, **payload):
        return (
            AgentRouteDecision(kind="answer", source="deterministic", intent="answer"),
            {"duration_ms": 0, "llm_called": False},
        )

    def run(self, **payload):
        return type(
            "Result",
            (),
            {
                "status": "completed",
                "plan": AgentPlan(action="answer", user_visible_reason="test"),
                "output_text": "finished",
                "provider": "test",
                "model": "test",
                "request_id": payload.get("request_id", 0),
                "tool_result": None,
                "route": AgentRouteDecision.model_validate(
                    payload["_resolved_route"]
                ),
            },
        )()


def _compiled_specialist(agent_id, run):
    def execute(state: _SpecialistState):
        return {"result": run(state["task"])}

    graph = StateGraph(_SpecialistState)
    graph.add_node(f"run_{agent_id}", execute)
    graph.add_edge(START, f"run_{agent_id}")
    graph.add_edge(f"run_{agent_id}", END)
    return graph.compile()


def _registry(agent_ids, runner):
    kind = ArtifactKind.DOCUMENT_ANALYSIS
    return AgentRegistry(
        tuple(
            AgentSpec(
                agent_id=agent_id,
                version="test-v1",
                display_name=f"{agent_id} Agent",
                description="test specialist",
                capabilities=frozenset({"test"}),
                accepted_input_kinds=frozenset({kind}),
                output_kinds=frozenset({kind}),
                allowed_tools=frozenset(),
                default_tools=(),
                default_output_kind=kind,
                graph_factory=lambda agent_id=agent_id: _compiled_specialist(
                    agent_id, runner
                ),
            )
            for agent_id in agent_ids
        )
    )


def _root(registry, task_definitions, *, calls, artifact_store=None):
    def provider(*, scope_ref, plan_revision, **_kwargs):
        tasks = []
        for task_id, agent_id, dependencies in task_definitions:
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
            "plan_id": f"send-plan-{plan_revision}",
            "plan_revision": plan_revision,
            "scope_ref": scope_ref,
            "tasks": [task.model_dump(mode="json") for task in tasks],
        }

    service = ResearchOrchestrationService(
        scope_resolver=_ScopeResolver(),
        executor=calls,
        router=_Router(),
        planner=ValidatedSupervisorPlanner(
            agent_registry=registry,
            provider=provider,
        ),
        memory_port=_Memory(),
        artifact_store=artifact_store,
    )
    bridge = MultiAgentRuntimeBridge(orchestrator=service)
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(_ProductService()),
        orchestration_service=service,
        collaboration_adapter=bridge,
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    return graph


def _state():
    return AgentState(
        user_input="run the native workflow",
        browser_context={
            "profile_id": "profile-send-test",
            "knowledge_document_ids": ["paper-a"],
            "multi_agent_mode": "force",
        },
    )


def test_compiled_native_root_passes_trace_to_specialist_without_wrapper():
    from backend.rag.observability import current_rag_trace

    observed = []

    def runner(task):
        observed.append(current_rag_trace())
        return TaskResult(task_id=task.task_id, attempt_id=f"{task.task_id}:1", status=TaskStatus.SUCCEEDED)

    graph = _root(_registry(["trace-agent"], runner), [("task-a", "trace-agent", ())], calls=_NeverExecutor())
    state = _state()
    def sink(*_args):
        return None
    result = graph.compiled_graph.invoke({"agent_state": state.model_dump(mode="json")},
        context={"event_sink": sink})
    assert TaskResult.model_validate(result["task_results"][0]).status is TaskStatus.SUCCEEDED, result["task_results"][0]
    assert observed == [(state.trace_id, sink)]
    assert current_rag_trace() == (None, None)


def test_native_send_runs_independent_tasks_in_parallel_and_waits_for_dependencies():
    barrier = Barrier(2, timeout=4)
    lock = Lock()
    starts: list[str] = []
    finishes: list[str] = []
    active = 0
    max_active = 0

    def runner(task):
        nonlocal active, max_active
        with lock:
            starts.append(task.task_id)
            active += 1
            max_active = max(max_active, active)
        if task.task_id in {"a", "c"}:
            barrier.wait()
        if task.task_id == "b":
            assert "a" in finishes
        with lock:
            finishes.append(task.task_id)
            active -= 1
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED,
        )

    legacy = _NeverExecutor()
    graph = _root(
        _registry(["a-agent", "b-agent", "c-agent"], runner),
        [
            ("a", "a-agent", ()),
            ("b", "b-agent", ("a",)),
            ("c", "c-agent", ()),
        ],
        calls=legacy,
    )
    result = graph.run_with_events(_state(), lambda *_args: None)

    assert max_active == 2
    assert starts.index("b") > finishes.index("a")
    parsed_results = [
        TaskResult.model_validate(item) for item in result.orchestration_results
    ]
    assert {item.task_id for item in parsed_results} == {"a", "b", "c"}
    assert all(item.status is TaskStatus.SUCCEEDED for item in parsed_results)
    assert legacy.calls == 0


def test_native_send_failure_is_reduced_and_blocks_only_its_descendant():
    barrier = Barrier(2, timeout=4)
    calls: list[str] = []
    lock = Lock()

    def runner(task):
        if task.task_id in {"a", "b"}:
            barrier.wait()
        with lock:
            calls.append(task.task_id)
        status = TaskStatus.FAILED if task.task_id == "b" else TaskStatus.SUCCEEDED
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=status,
            error_code="mock_failure" if status is TaskStatus.FAILED else "",
        )

    legacy = _NeverExecutor()
    graph = _root(
        _registry(["a-agent", "b-agent", "c-agent", "d-agent"], runner),
        [
            ("a", "a-agent", ()),
            ("b", "b-agent", ()),
            ("c", "c-agent", ("a",)),
            ("d", "d-agent", ("b",)),
        ],
        calls=legacy,
    )
    result = graph.run_with_events(_state(), lambda *_args: None)
    statuses = {
        item.task_id: item.status
        for item in map(TaskResult.model_validate, result.orchestration_results)
    }

    assert statuses == {
        "a": TaskStatus.SUCCEEDED,
        "b": TaskStatus.FAILED,
        "c": TaskStatus.SUCCEEDED,
        "d": TaskStatus.BLOCKED,
    }
    assert set(calls) == {"a", "b", "c"}
    assert legacy.calls == 0


def test_native_root_loads_only_verified_scoped_artifact_outputs():
    store = InMemoryArtifactStore()

    def runner(task):
        artifact = store.put(
            Artifact(
                artifact_id=f"artifact-{task.task_id}",
                producer_task_id=task.task_id,
                kind=ArtifactKind.DOCUMENT_ANALYSIS,
                scope_ref=task.scope_ref,
                content={"summary": "scoped output"},
                verification_status=VerificationStatus.PASSED,
            )
        )
        return TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[artifact.ref()],
        )

    legacy = _NeverExecutor()
    graph = _root(
        _registry(["artifact-agent"], runner),
        [("artifact-task", "artifact-agent", ())],
        calls=legacy,
        artifact_store=store,
    )
    result = graph.run_with_events(_state(), lambda *_args: None)

    payload = result.browser_context["orchestration_context"]["specialists"][0]["output"]
    assert payload["scope_ref"] == result.orchestration_scope["scope_ref"]
    assert payload["content"] == {"summary": "scoped output"}
    assert legacy.calls == 0
