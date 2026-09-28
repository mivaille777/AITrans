from __future__ import annotations

from typing import Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.agent_registry import AgentRegistry, AgentSpec
from backend.agent_core.orchestration.parallel_executor import (
    ParallelExecutionPolicy,
    ParallelTaskGraphExecutor,
)
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus
from backend.models.agent_tools import AgentPlan
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class _MockState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    result: TaskResult


class _NoLegacyExecution:
    policy = ParallelExecutionPolicy()

    def __init__(self):
        self.calls = 0

    def execute(self, **_kwargs):
        self.calls += 1
        raise AssertionError("the native Mock Agent must not use the old scheduler")


class _Router:
    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.SINGLE,
            reason_code="dynamic-mock-agent",
        )


class _ScopeResolver:
    def resolve(self, *, profile_id="", memory_policy_revision="", **_kwargs):
        return ScopeContext.issue(
            profile_id=profile_id,
            scope_revision="dynamic-mock-v1",
            memory_policy_revision=memory_policy_revision,
            allowed_document_ids=["paper-a"],
        )


class _Memory:
    def policy_revision(self, _profile_id):
        return "memory-policy:dynamic-mock-v1"

    def load_snapshot(self, *, profile_id, scope, **_kwargs):
        return {
            "status": "ready",
            "snapshot_id": "dynamic-mock-memory",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
            "policy_revision": scope.memory_policy_revision,
            "role_projections": {"mock_data": [{"content": "scoped memory"}]},
        }

    def submit_candidates(self, **_kwargs):
        return None


class _Product:
    def resolve_route(self, **_payload):
        return (
            AgentRouteDecision(kind="answer", source="deterministic", intent="answer"),
            {"duration_ms": 0, "llm_called": False},
        )

    def run(self, **payload):
        return type(
            "ProductResult",
            (),
            {
                "status": "completed",
                "plan": AgentPlan(action="answer", user_visible_reason="done"),
                "output_text": "done",
                "provider": "test",
                "model": "test",
                "request_id": payload.get("request_id", 0),
                "tool_result": None,
                "route": AgentRouteDecision.model_validate(
                    payload["_resolved_route"]
                ),
            },
        )()


def _spec(graph_factory):
    kind = ArtifactKind.DOCUMENT_ANALYSIS
    return AgentSpec(
        agent_id="mock_data",
        version="test-v1",
        display_name="Mock Data Agent",
        description="Dynamic structured-data specialist for tests.",
        capabilities=frozenset({"structured_data"}),
        accepted_input_kinds=frozenset({kind}),
        output_kinds=frozenset({kind}),
        allowed_tools=frozenset({"read_mock_data"}),
        default_tools=("read_mock_data",),
        default_output_kind=kind,
        graph_factory=graph_factory,
        resource_class="cpu",
    )


def _build(*, mutation=""):
    invocations: list[dict[str, Any]] = []

    def execute(state: _MockState):
        invocations.append(state)
        return {
            "result": TaskResult(
                task_id=state["task"].task_id,
                attempt_id=f"{state['task'].task_id}:1",
                status=TaskStatus.SUCCEEDED,
            )
        }

    child = StateGraph(_MockState)
    child.add_node("read_mock_data", execute)
    child.add_edge(START, "read_mock_data")
    child.add_edge("read_mock_data", END)
    compiled_child = child.compile()
    factory_calls = 0

    def graph_factory():
        nonlocal factory_calls
        factory_calls += 1
        return compiled_child

    registry = AgentRegistry((_spec(graph_factory),))

    def provider(*, scope_ref, plan_revision, **_kwargs):
        agent_id = "not_registered" if mutation == "agent" else "mock_data"
        allowed_tools = (
            ["delete_all_data"] if mutation == "tool" else ["read_mock_data"]
        )
        targets = ["outside-scope"] if mutation == "scope" else []
        task = TaskSpec(
            task_id="mock-task-1",
            agent_id=agent_id,
            objective="Inspect the selected structured data.",
            required=True,
            expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
            scope_ref=scope_ref,
            allowed_tools=allowed_tools,
            target_source_ids=targets,
            plan_revision=plan_revision,
        )
        return {
            "plan_id": f"mock-plan-{plan_revision}",
            "plan_revision": plan_revision,
            "scope_ref": scope_ref,
            "tasks": [task.model_dump(mode="json")],
        }

    legacy = _NoLegacyExecution()
    service = ResearchOrchestrationService(
        scope_resolver=_ScopeResolver(),
        executor=legacy,
        router=_Router(),
        planner=ValidatedSupervisorPlanner(
            agent_registry=registry,
            provider=provider,
        ),
        memory_port=_Memory(),
    )
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(_Product()),
        orchestration_service=service,
        collaboration_adapter=MultiAgentRuntimeBridge(orchestrator=service),
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    state = AgentState(
        user_input="read selected mock data",
        browser_context={
            "profile_id": "profile-mock",
            "knowledge_document_ids": ["paper-a"],
            "multi_agent_mode": "force",
        },
    )
    return graph, state, invocations, legacy, factory_calls


def test_planner_discovered_dynamic_mock_agent_executes_once_on_native_send(monkeypatch):
    graph, state, invocations, legacy, factory_calls = _build()
    legacy_executor = ParallelTaskGraphExecutor({})
    graph._orchestration_service.executor = legacy_executor
    legacy_calls: list[str] = []

    def reject_legacy_execute(_self, **_kwargs):
        legacy_calls.append("called")
        raise AssertionError("native run entered ParallelTaskGraphExecutor.execute")

    monkeypatch.setattr(ParallelTaskGraphExecutor, "execute", reject_legacy_execute)
    result = graph.run_with_events(state, lambda *_args: None)

    assert factory_calls == 1
    assert len(invocations) == 1
    assert invocations[0]["task"].agent_id == "mock_data"
    assert invocations[0]["task"].role is None
    assert invocations[0]["memory_snapshot"]["role_projections"]["mock_data"]
    assert TaskResult.model_validate(result.orchestration_results[0]).status is TaskStatus.SUCCEEDED
    assert result.orchestration_plan["tasks"][0]["agent_id"] == "mock_data"
    assert result.orchestration_plan["tasks"][0]["role"] is None
    assert legacy.calls == 0
    assert legacy_calls == []


@pytest.mark.parametrize("mutation", ["agent", "tool", "scope"])
def test_native_plan_rejections_happen_before_specialist_graph_invocation(mutation):
    graph, state, invocations, _legacy, _factory_calls = _build(mutation=mutation)

    with pytest.raises((ValueError, KeyError)):
        graph.run_with_events(state, lambda *_args: None)

    assert invocations == []
