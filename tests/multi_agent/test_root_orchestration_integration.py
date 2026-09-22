from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.agent_core.orchestration.scope_resolver import AuthoritativeScopeResolver
from backend.agent_core.orchestration.serial_executor import (
    SerialTaskGraphExecutor,
    SpecialistExecution,
)
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import TaskResult, TaskRole, TaskStatus
from backend.models.agent_tools import AgentPlan
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class Workspaces:
    def get(self, workspace_id: str):
        if workspace_id != "workspace-a":
            return None
        return SimpleNamespace(
            document_ids=("doc-a", "doc-b"),
            note_ids=(),
            conversation_ids=(),
        )


class Memory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def load_snapshot(self, *, profile_id, scope):
        self.calls.append((profile_id, scope.scope_ref))
        return {"snapshot_id": "memory-snapshot-1", "status": "available"}


class Specialist:
    def execute(self, *, task, scope, dependency_results, memory_snapshot):
        assert memory_snapshot["snapshot_id"] == "memory-snapshot-1"
        return SpecialistExecution(
            result=TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:1",
                status=TaskStatus.SUCCEEDED,
            ),
            output={"task_id": task.task_id, "scope_ref": scope.scope_ref},
        )


def test_bridge_freezes_scope_memory_and_task_state_without_mutating_reading_context() -> None:
    memory = Memory()
    specialist = Specialist()
    service = ResearchOrchestrationService(
        scope_resolver=AuthoritativeScopeResolver(research_workspaces=Workspaces()),
        executor=SerialTaskGraphExecutor(
            {TaskRole.DOCUMENT: specialist, TaskRole.RESEARCH: specialist}
        ),
        router=ResearchTaskRouter(),
        planner=ValidatedSupervisorPlanner(),
        memory_port=memory,
    )
    bridge = MultiAgentRuntimeBridge(orchestrator=service)
    state = AgentState(
        session_id="volatile-session-id",
        user_input="比较两篇论文的实验结果",
        browser_context={
            "profile_id": "profile-stable",
            "workspace_id": "workspace-a",
            "knowledge_document_ids": ["doc-a", "doc-b"],
            "context_before": "original reading context",
        },
    )
    events = []

    result = bridge.run_with_events(state, lambda kind, payload: events.append((kind, payload)))

    assert result.orchestration_lane == "workflow"
    assert result.orchestration_status == "completed"
    assert result.memory_snapshot_ref == "memory-snapshot-1"
    assert result.orchestration_scope["allowed_document_ids"] == ["doc-a", "doc-b"]
    assert result.planned_action["action"] == "answer"
    assert (
        result.planned_action["arguments"]["orchestration_plan_id"]
        == result.orchestration_plan["plan_id"]
    )
    assert [item["task_id"] for item in result.orchestration_results] == [
        "document-1",
        "document-2",
        "research-1",
    ]
    assert result.browser_context["context_before"] == "original reading context"
    assert "orchestration_context" in result.browser_context
    assert memory.calls == [("profile-stable", result.orchestration_scope["scope_ref"])]
    assert events


class ProductService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

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


class Conversations:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def begin(self, _state):
        self.calls.append("begin")
        return SimpleNamespace(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            history=(),
            owner_id="owner-1",
            request_id=1,
        )

    def apply_to_state(self, state, run):
        self.calls.append("apply")
        return state.apply_conversation(conversation_id=run.conversation_id, history=())

    def complete(self, _run, _state):
        self.calls.append("complete")

    def fail(self, _run, _exc):
        self.calls.append("fail")


class Collaboration:
    @staticmethod
    def should_run(_state):
        return True

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run_with_events(self, state, _emit, *, control=None):
        del control
        assert self.calls[:2] == ["begin", "apply"]
        self.calls.append("collaboration")
        return state


class DirectDeliveryCollaboration:
    @staticmethod
    def should_run(_state):
        return True

    def run_with_events(self, state, _emit, *, control=None):
        del control
        context = dict(state.browser_context)
        context["orchestration_direct_delivery"] = True
        state.browser_context = context
        state.apply_response(
            {
                "status": "completed",
                "output_text": "bounded tool output",
                "provider": "orchestration-tool",
                "model": "",
                "request_id": 1,
            }
        )
        return state


def test_root_graph_acquires_conversation_ownership_before_specialists() -> None:
    calls: list[str] = []
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(
            ProductService(calls),
            conversation_service=Conversations(calls),
        ),
        collaboration_adapter=Collaboration(calls),
    )

    AgentRuntime(workflow_adapter=graph).execute(
        AgentState(user_input="analyze", browser_context={"request_id": 1})
    )

    assert calls == ["begin", "apply", "collaboration", "route", "product", "complete"]


def test_root_graph_delivers_completed_bounded_output_without_second_generation() -> None:
    calls: list[str] = []
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(
            ProductService(calls),
            conversation_service=Conversations(calls),
        ),
        collaboration_adapter=DirectDeliveryCollaboration(),
    )

    result = AgentRuntime(workflow_adapter=graph).execute(
        AgentState(user_input="bounded task", browser_context={"request_id": 1})
    )

    assert result.response["output_text"] == "bounded tool output"
    assert "route" not in calls
    assert "product" not in calls
    assert calls == ["begin", "apply", "complete"]
