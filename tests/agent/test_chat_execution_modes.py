from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import AgentReActDecision
from backend.models.agent_runtime import (
    AgentPlanContext,
    AgentPlanStep,
    AgentRouteDecision,
)
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec


class PlannedService:
    def __init__(self):
        self.executions = []
        self.planning_calls = 0

    def list_tools(self):
        return (
            AgentToolSpec(
                name="inspect_reading_context",
                title="Inspect",
                description="Read selection",
                category="reading",
                effect="read",
                requires_reading_context=True,
                requires_confirmation=False,
                input_schema={},
            ),
        )

    def plan_multi_step(self, **payload):
        self.planning_calls += 1
        return AgentPlanContext(
            goal="Inspect selected text",
            mode="multi_step",
            steps=[
                AgentPlanStep(step_id="step-1", tool_name="inspect_reading_context")
            ],
        ), {}

    def run(self, **payload):
        route = AgentRouteDecision.model_validate(payload["_resolved_route"])
        self.executions.append(route.tool_name)
        result = AgentToolExecutionResult(
            tool_name=route.tool_name,
            output_text="Observed text",
            effect="read",
            data={},
            verification={"status": "passed", "checks": [{"code": "test_readback", "status": "passed"}]},
        )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="tool", tool_name=route.tool_name),
            tool_result=result,
            request_id=1,
        )

    def synthesize_multi_step(self, **payload):
        return SimpleNamespace(
            status="completed",
            output_text="Completed approved steps",
            provider="stub",
            model="stub",
            request_id=1,
        )


def prepared(conversation_service=None, mode="plan_execute", service=None):
    service = service or PlannedService()

    class FinalDecision:
        def decide(self, **_payload):
            return AgentReActDecision(
                iteration=1, kind="final", final_answer="A direct answer"
            )

    graph = ReadingAgentGraph(
        ProductAgentRuntimeAdapter(service, conversation_service=conversation_service),
        checkpointer=InMemorySaver(),
        react_decision_service=FinalDecision(),
    )
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(
        session_id="chat-plan",
        user_input="Inspect this text",
        selected_text="A finding",
        browser_context={
            "execution_mode": mode,
            "context_mode": "reading",
            "request_id": 1,
        },
    )
    result = runtime.execute(state)
    return service, runtime, result


def test_plan_waits_and_executes_exact_plan_after_confirmation():
    service, runtime, result = prepared()
    assert result.response["status"] == "confirmation_required"
    assert service.executions == []
    checkpoint = runtime.restore_checkpoint(result.run_id)
    assert checkpoint.browser_context["pending_plan_confirmation"]["plan_hash"]
    checkpoint.browser_context["plan_confirmation_decision"] = {
        "decision": "approve",
        "plan_hash": checkpoint.browser_context["pending_plan_confirmation"][
            "plan_hash"
        ],
    }
    completed = runtime.execute(checkpoint, resume=True)
    assert completed.response["status"] == "completed"
    assert service.planning_calls == 1
    assert service.executions == ["inspect_reading_context"]
    assert completed.plan.steps[0].status == "completed"


def test_react_answers_without_requesting_plan_approval():
    service, _runtime, result = prepared(mode="react")
    assert result.response["status"] == "completed"
    assert result.response["output_text"] == "A direct answer"
    assert service.planning_calls == 0
    assert "pending_plan_confirmation" not in result.browser_context


def test_failed_verified_step_stops_approved_plan_dependencies():
    from dataclasses import replace
    class FailedService(PlannedService):
        def plan_multi_step(self, **payload):
            plan, metadata = super().plan_multi_step(**payload)
            plan.steps.append(AgentPlanStep(step_id="step-2", tool_name="inspect_reading_context", depends_on=["step-1"]))
            return plan, metadata
        def run(self, **payload):
            response = super().run(**payload)
            response.tool_result = replace(response.tool_result, status="failed", verification={"status": "failed", "checks": []})
            return response
    service, runtime, pending = prepared(service=FailedService())
    checkpoint = runtime.restore_checkpoint(pending.run_id)
    checkpoint.browser_context["plan_confirmation_decision"] = {"decision": "approve", "plan_hash": checkpoint.browser_context["pending_plan_confirmation"]["plan_hash"]}
    completed = runtime.execute(checkpoint, resume=True)
    assert service.executions == ["inspect_reading_context"]
    assert completed.plan.steps[0].status == "failed" and completed.plan.steps[1].status == "pending"
    assert completed.browser_context["task_completion"]["status"] != "completed"


def test_api_checks_plan_fingerprint_before_consuming_approval(monkeypatch):
    from backend.api.agent import _apply_resume_request_context
    from backend.models.agent_tools import AgentRunRequest

    _service, runtime, result = prepared()
    checkpoint = runtime.restore_checkpoint(result.run_id)
    payload = AgentRunRequest(
        session_id=checkpoint.session_id,
        conversation_id=checkpoint.conversation.conversation_id,
        user_message="approve",
        resume_run_id=result.run_id,
        plan_confirmation="approve",
        plan_hash="wrong",
    )
    with pytest.raises(ValueError, match="计划确认"):
        _apply_resume_request_context(checkpoint, payload)


def test_chat_request_uses_server_configuration(monkeypatch, tmp_path):
    from backend.api import chat_sessions
    from backend.api.agent import _state_from_run_request
    from backend.models.agent_tools import AgentRunRequest
    from backend.services.chat_session_service import ChatSessionService
    from backend.services.filesystem_workspace_service import FilesystemWorkspaceService

    service = ChatSessionService(
        FilesystemWorkspaceService(tmp_path / "workspace.sqlite3"),
        tmp_path / "chat.sqlite3",
    )
    service.update("server-session", execution_mode="plan_execute")
    monkeypatch.setattr(chat_sessions, "get_chat_session_service", lambda: service)
    state = _state_from_run_request(
        AgentRunRequest(
            session_id="server-session",
            user_message="QA",
            chat_configuration=True,
            filesystem_workspace_id="forged-workspace",
            execution_mode="react",
        )
    )
    assert state.browser_context["execution_mode"] == "plan_execute"
    assert state.browser_context["filesystem_workspace_id"] == ""
    service.set_pending_run("server-session", "waiting-run")
    with pytest.raises(ValueError, match="当前计划"):
        _state_from_run_request(
            AgentRunRequest(
                session_id="server-session", user_message="QA", chat_configuration=True
            )
        )


def test_cancel_plan_does_not_execute_tools():
    service, runtime, result = prepared()
    checkpoint = runtime.restore_checkpoint(result.run_id)
    checkpoint.browser_context["plan_confirmation_decision"] = {
        "decision": "reject",
        "plan_hash": checkpoint.browser_context["pending_plan_confirmation"][
            "plan_hash"
        ],
    }
    completed = runtime.execute(checkpoint, resume=True)
    assert "取消" in completed.response["output_text"]
    assert service.executions == []


def test_confirmation_cannot_substitute_a_different_plan():
    service, runtime, result = prepared()
    checkpoint = runtime.restore_checkpoint(result.run_id)
    checkpoint.browser_context["plan_confirmation_decision"] = {
        "decision": "approve",
        "plan_hash": "wrong",
    }
    with pytest.raises(Exception, match="计划确认"):
        runtime.execute(checkpoint, resume=True)
    assert service.executions == []


def test_pending_plan_and_user_message_survive_conversation_reload(tmp_path):
    from backend.services.agent_conversation_service import AgentConversationService
    from backend.services.companion_ownership_service import (
        CompanionConversationOwnershipService,
    )
    from backend.services.conversation_lifecycle_service import (
        ConversationLifecycleService,
    )

    store = ConversationLifecycleService(
        storage_path=tmp_path / "conversations.sqlite3"
    )
    conversations = AgentConversationService(
        store=store, ownership=CompanionConversationOwnershipService()
    )
    service, runtime, result = prepared(conversations)
    saved = store.get(result.conversation.conversation_id)
    assert [message.role for message in saved.messages] == ["user", "assistant"]
    assert "计划目标" in saved.messages[1].content
    assert service.executions == []
    checkpoint = runtime.restore_checkpoint(result.run_id)
    checkpoint.browser_context["plan_confirmation_decision"] = {
        "decision": "approve",
        "plan_hash": checkpoint.browser_context["pending_plan_confirmation"][
            "plan_hash"
        ],
    }
    runtime.execute(checkpoint, resume=True)
    saved = store.get(result.conversation.conversation_id)
    assert saved.messages[0].content == "Inspect this text"
    assert saved.messages[1].content == "Completed approved steps"
