from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.agent_core.exceptions import AgentRuntimeError
from backend.agent_core.orchestration.coordinator_memory import CoordinatorMemoryPort
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.agent_core.orchestration.scope_resolver import AuthoritativeScopeResolver
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.agent_orchestration import OrchestrationLane
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import TaskResult, TaskStatus
from backend.models.agent_tools import AgentPlan
from backend.models.memory import MemoryKind
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class _RecordingSaver(InMemorySaver):
    def __init__(self) -> None:
        super().__init__()
        self.checkpoint_values: list[dict] = []

    def put(self, config, checkpoint, metadata, new_versions):
        self.checkpoint_values.append(deepcopy(checkpoint.get("channel_values", {})))
        return super().put(config, checkpoint, metadata, new_versions)


class _Conversations:
    def begin(self, _state):
        return SimpleNamespace(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            history=(),
            owner_id="owner-1",
            request_id=1,
        )

    def apply_to_state(self, state, run):
        return state.apply_conversation(
            conversation_id=run.conversation_id, history=()
        )

    def complete(self, _run, _state):
        return None

    def fail(self, _run, _exc):
        return None


class _ProductService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve_route(self, **_payload):
        self.calls.append("route")
        return (
            AgentRouteDecision(kind="answer", source="deterministic", intent="answer"),
            {},
        )

    def run(self, **payload):
        self.calls.append("product")
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="answer", user_visible_reason="done"),
            output_text="done",
            provider="fake",
            model="fake",
            request_id=payload.get("request_id", 0),
            tool_result=None,
            route=AgentRouteDecision.model_validate(payload["_resolved_route"]),
        )


class _CountingRouter:
    def __init__(self) -> None:
        self.inner = ResearchTaskRouter()
        self.calls = 0

    def route(self, *args, **kwargs):
        self.calls += 1
        return self.inner.route(*args, **kwargs)


class _CountingScopeResolver:
    def __init__(self, inner: AuthoritativeScopeResolver | None = None) -> None:
        self.inner = inner or AuthoritativeScopeResolver()
        self.calls = 0

    def resolve(self, **kwargs):
        self.calls += 1
        return self.inner.resolve(**kwargs)


class _CountingPlanner:
    def __init__(self) -> None:
        self.inner = ValidatedSupervisorPlanner()
        self.plan_calls = 0
        self.validate_calls = 0

    def plan(self, **kwargs):
        self.plan_calls += 1
        return self.inner.plan(**kwargs)

    def validate(self, *args, **kwargs):
        self.validate_calls += 1
        return self.inner.validate(*args, **kwargs)


class _Memory:
    def __init__(self, *, status: str = "ready") -> None:
        self.status = status
        self.calls = 0
        self.candidate_calls = 0

    def policy_revision(self, _profile_id: str) -> str:
        return "memory-policy:test-v1"

    def load_snapshot(self, *, profile_id, scope, run_id="", temporary=False):
        del run_id, temporary
        self.calls += 1
        snapshot = {
            "status": self.status,
            "snapshot_id": "memory-snapshot-1",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
            "policy_revision": scope.memory_policy_revision,
        }
        if self.status == "memory_read_disabled":
            snapshot["status"] = "unavailable"
            snapshot["reason_code"] = "memory_read_disabled"
        return snapshot

    def submit_candidates(self, **_kwargs):
        self.candidate_calls += 1


class _Executor:
    def __init__(self) -> None:
        self.graph: RootAgentGraph | None = None
        self.calls: list[list[str]] = []

    def execute(self, *, plan, scope, memory_snapshot, run_id, collector, control):
        del collector, control
        assert memory_snapshot["snapshot_id"] == "memory-snapshot-1"
        if self.graph is not None:
            assert any(
                snapshot.get("task_plan", {}).get("plan_id") == plan.plan_id
                and snapshot.get("scope", {}).get("scope_ref") == scope.scope_ref
                and snapshot.get("plan_revision") == plan.plan_revision
                and snapshot.get("memory_policy_revision")
                == scope.memory_policy_revision
                for snapshot in self.graph._checkpointer.checkpoint_values
            ), (
                "validated Root plan and Scope must be checkpointed before executor entry",
                [
                    (
                        item.get("task_plan"),
                        item.get("proposed_task_plan"),
                        item.get("orchestration_status"),
                    )
                    for item in self.graph._checkpointer.checkpoint_values
                ],
            )
        self.calls.append([task.task_id for task in plan.tasks])
        results = tuple(
            TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:1",
                status=TaskStatus.SUCCEEDED,
            )
            for task in plan.tasks
        )
        return SimpleNamespace(
            results=results,
            outputs={task.task_id: {"ok": True} for task in plan.tasks},
            direct_output=None,
            direct_delivery=False,
        )


def _stack(*, memory: _Memory | None = None):
    router = _CountingRouter()
    resolver = _CountingScopeResolver()
    planner = _CountingPlanner()
    selected_memory = memory or _Memory()
    executor = _Executor()
    service = ResearchOrchestrationService(
        scope_resolver=resolver,
        executor=executor,
        router=router,
        planner=planner,
        memory_port=selected_memory,
    )
    bridge = MultiAgentRuntimeBridge(
        orchestrator=service, maximum_lane=OrchestrationLane.WORKFLOW
    )
    product = _ProductService()
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(product, conversation_service=_Conversations()),
        checkpointer=_RecordingSaver(),
        collaboration_adapter=bridge,
        orchestration_service=service,
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    executor.graph = graph
    return graph, service, router, resolver, planner, selected_memory, executor, product


@pytest.mark.parametrize(
    ("goal", "documents", "lane", "task_count"),
    [
        ("总结这篇论文的方法", ["paper-a"], OrchestrationLane.SINGLE, 1),
        (
            "比较两篇论文的实验结果",
            ["paper-a", "paper-b"],
            OrchestrationLane.WORKFLOW,
            3,
        ),
    ],
)
def test_native_root_plans_once_and_checkpoints_before_legacy_executor(
    goal, documents, lane, task_count
):
    graph, _service, router, resolver, planner, memory, executor, _product = _stack()
    state = AgentState(
        user_input=goal,
        browser_context={
            "profile_id": "profile-a",
            "knowledge_document_ids": documents,
            "multi_agent_mode": "auto",
        },
    )

    result = graph.run_with_events(state, lambda *_args: None)

    assert router.calls == 1
    assert resolver.calls == 1
    assert planner.plan_calls == 1
    assert planner.validate_calls == 1
    assert memory.calls == 1
    assert len(executor.calls[0]) == task_count
    assert result.orchestration_lane == lane.value
    assert result.orchestration_plan["scope_ref"] == result.orchestration_scope["scope_ref"]


def test_native_fast_and_missing_information_routes_do_not_call_specialists():
    fast = _stack()
    fast_graph, _, fast_router, fast_scope, fast_planner, fast_memory, fast_executor, _ = fast
    fast_state = AgentState(
        user_input="翻译这段文字",
        selected_text="A short passage.",
        browser_context={"profile_id": "profile-a"},
    )
    fast_graph.run_with_events(fast_state, lambda *_args: None)
    assert fast_router.calls == 1
    assert fast_scope.calls == fast_planner.plan_calls == fast_memory.calls == 0
    assert fast_executor.calls == []

    blocked = _stack()
    blocked_graph, _, _, blocked_scope, blocked_planner, blocked_memory, blocked_executor, blocked_product = blocked
    blocked_state = AgentState(
        user_input="比较这些论文",
        browser_context={"profile_id": "profile-a"},
    )
    result = blocked_graph.run_with_events(blocked_state, lambda *_args: None)
    assert result.orchestration_status == "blocked"
    assert result.response_state.status == "completed"
    assert blocked_scope.calls == blocked_planner.plan_calls == blocked_memory.calls == 0
    assert blocked_executor.calls == []
    assert blocked_product.calls == []


@pytest.mark.parametrize("memory_status", ["invalidated", "memory_read_disabled"])
def test_native_memory_failure_stops_before_planning_or_artifact_submission(memory_status):
    memory = _Memory(status=memory_status)
    graph, _, _, resolver, planner, memory, executor, _ = _stack(memory=memory)
    state = AgentState(
        user_input="总结这篇论文的方法",
        browser_context={
            "profile_id": "profile-a",
            "knowledge_document_ids": ["paper-a"],
        },
    )

    with pytest.raises(AgentRuntimeError):
        graph.run_with_events(state, lambda *_args: None)

    assert resolver.calls == 1
    assert planner.plan_calls == 0
    assert executor.calls == []
    assert memory.candidate_calls == 0


def test_ma04_and_ma05_compat_runs_keep_the_compatibility_topology():
    for version in ("reading-agent-ma04-v1", CURRENT_AGENT_GRAPH_VERSION):
        graph = RootAgentGraph(
            ProductAgentRuntimeAdapter(_ProductService()),
            graph_version=version,
            engine="native" if version == "reading-agent-ma04-v1" else "compat",
        )
        nodes = set(graph.compiled_graph.get_graph().nodes)
        edges = {
            (edge.source, edge.target)
            for edge in graph.compiled_graph.get_graph().edges
        }

        assert "route_orchestration" not in nodes
        assert ("prepare_conversation", "run_collaboration") in edges


def test_native_scope_failure_aborts_before_memory_or_specialists():
    graph, _service, _router, resolver, planner, memory, executor, _ = _stack()
    state = AgentState(
        user_input="总结这篇论文的方法",
        browser_context={
            "profile_id": "profile-a",
            "workspace_id": "workspace-missing",
            "knowledge_document_ids": ["paper-a"],
        },
    )

    with pytest.raises(ValueError, match="research workspace"):
        graph.run_with_events(state, lambda *_args: None)

    assert resolver.calls == 1
    assert planner.plan_calls == 0
    assert memory.calls == 0
    assert executor.calls == []
    assert memory.candidate_calls == 0


def test_resume_revalidates_scope_and_revoked_memory_before_executor(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    item = coordinator.remember(
        operation_id="memory-before-resume",
        profile_id="profile-a",
        kind=MemoryKind.TERMINOLOGY,
        content="PRIVATE-TERM",
        source_ref="user:term",
    )
    resolver = _CountingScopeResolver()
    executor = _Executor()
    service = ResearchOrchestrationService(
        scope_resolver=resolver,
        executor=executor,
        memory_port=CoordinatorMemoryPort(coordinator),
    )
    context = {"knowledge_document_ids": ["paper-a"]}
    route = service.route("总结这篇论文的方法", context)
    scope = service.resolve_scope(profile_id="profile-a", runtime_context=context)
    memory_snapshot = service.load_memory_snapshot(
        profile_id="profile-a",
        scope=scope,
        run_id="resume-run",
        runtime_context=context,
    )
    task_plan = service.plan_tasks(
        route=route,
        objective="总结这篇论文的方法",
        scope=scope,
    )
    assert task_plan is not None
    service.validate_plan(task_plan, scope=scope)
    coordinator.forget(profile_id="profile-a", item_id=item.item_id, expected_version=1)

    with pytest.raises(AgentRuntimeError) as exc_info:
        service.execute_prepared(
            route=route,
            scope=scope,
            memory_snapshot=memory_snapshot,
            task_plan=task_plan,
            profile_id="profile-a",
            run_id="resume-run",
            trace_id="trace-resume",
            runtime_context=context,
            resuming=True,
        )

    assert exc_info.value.fallback_reason == "memory_snapshot_invalidated"
    assert resolver.calls == 2
    assert executor.calls == []


def test_resume_rejects_changed_memory_permissions_before_executor(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory-policy.sqlite3")
    coordinator = MemoryCoordinator(repository)
    resolver = _CountingScopeResolver()
    executor = _Executor()
    service = ResearchOrchestrationService(
        scope_resolver=resolver,
        executor=executor,
        memory_port=CoordinatorMemoryPort(coordinator),
    )
    context = {"knowledge_document_ids": ["paper-a"]}
    route = service.route("总结这篇论文的方法", context)
    scope = service.resolve_scope(profile_id="profile-a", runtime_context=context)
    snapshot = service.load_memory_snapshot(
        profile_id="profile-a",
        scope=scope,
        run_id="policy-run",
        runtime_context=context,
    )
    plan = service.plan_tasks(route=route, objective="总结这篇论文的方法", scope=scope)
    assert plan is not None
    service.validate_plan(plan, scope=scope)
    coordinator.remember(
        operation_id="create-policy-profile",
        profile_id="profile-a",
        kind=MemoryKind.TERMINOLOGY,
        content="temporary profile row",
        source_ref="user:policy",
    )
    with repository._connect() as connection:
        connection.execute(
            "UPDATE memory_profiles SET read_enabled=0 WHERE profile_id=?",
            ("profile-a",),
        )

    with pytest.raises(AgentRuntimeError) as exc_info:
        service.execute_prepared(
            route=route,
            scope=scope,
            memory_snapshot=snapshot,
            task_plan=plan,
            profile_id="profile-a",
            run_id="policy-run",
            trace_id="trace-policy",
            runtime_context=context,
            resuming=True,
        )

    assert exc_info.value.fallback_reason == "prepared_scope_changed"
    assert resolver.calls == 2
    assert executor.calls == []
