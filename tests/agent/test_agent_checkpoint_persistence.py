from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentRuntimeError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.agent_tool_registry import AgentToolSpec

WRITE_TOOL = AgentToolSpec(
    name="save_research_note",
    title="Save note",
    description="Persist a research note.",
    category="research",
    effect="write",
    requires_reading_context=False,
    requires_confirmation=True,
    input_schema={},
)


class ConversationProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def begin(self, state: AgentState):
        self.calls.append("begin")
        return SimpleNamespace(
            conversation_id="conversation-checkpoint",
            user_message_id="user-checkpoint",
            assistant_message_id="assistant-checkpoint",
            history=(),
            owner_id="agent:checkpoint",
            request_id=17,
        )

    def apply_to_state(self, state: AgentState, run):
        self.calls.append("apply")
        return state.apply_conversation(
            conversation_id=run.conversation_id,
            history=run.history,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
        )

    def complete(self, _run, _state: AgentState) -> None:
        self.calls.append("complete")

    def fail(self, _run, _exc: Exception) -> None:
        self.calls.append("fail")

    def cancel(self, _run) -> None:
        self.calls.append("cancel")


class DirectAnswerService:
    def __init__(self, *, interrupt_route: bool = False) -> None:
        self.interrupt_route = interrupt_route
        self.route_calls = 0
        self.run_calls = 0

    def resolve_route(self, **_payload):
        self.route_calls += 1
        if self.interrupt_route:
            raise KeyboardInterrupt("simulated process interruption")
        return (
            AgentRouteDecision(
                kind="answer",
                source="deterministic",
                intent="answer",
                user_visible_reason="Answer directly.",
            ),
            {"llm_called": False},
        )

    def run(self, *, event_sink=None, **payload):
        self.run_calls += 1
        if event_sink is not None:
            event_sink(
                "plan_ready",
                {
                    "action": "answer",
                    "tool_name": "",
                    "request_id": payload.get("request_id", 0),
                },
            )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="answer",
                user_visible_reason="Recovered answer.",
            ),
            output_text="Recovered from the durable checkpoint.",
            provider="fake",
            model="fake-model",
            request_id=payload.get("request_id", 0),
            tool_result=None,
            route=AgentRouteDecision.model_validate(payload["_resolved_route"]),
        )


class InterruptedWriteService(DirectAnswerService):
    def list_tools(self):
        return (WRITE_TOOL,)

    def resolve_route(self, **_payload):
        self.route_calls += 1
        return (
            AgentRouteDecision(
                kind="tool",
                source="deterministic",
                intent="save_research_note",
                tool_name="save_research_note",
                user_visible_reason="Save the note after confirmation.",
            ),
            {"llm_called": False},
        )

    def run(self, **_payload):
        raise KeyboardInterrupt("simulated interruption before write result")


class ContextProviderProbe:
    def __init__(self, *, interrupt: bool = False) -> None:
        self.interrupt = interrupt
        self.calls = 0

    def __call__(self, state: AgentState) -> dict:
        self.calls += 1
        if self.interrupt:
            raise KeyboardInterrupt("simulated context interruption")
        return {
            **state.browser_context,
            "context_before": "restored context",
        }


class CollaborationProbe:
    def __init__(self, *, interrupt: bool = False) -> None:
        self.interrupt = interrupt
        self.calls = 0

    @staticmethod
    def should_run(_state: AgentState) -> bool:
        return True

    def run_with_events(self, state: AgentState, emit, *, control=None) -> AgentState:
        self.calls += 1
        if self.interrupt:
            raise KeyboardInterrupt("simulated collaboration interruption")
        state.browser_context["multi_agent_context"] = {"status": "restored"}
        emit(
            AgentEventType.MULTI_AGENT_COMPLETED,
            {"status": "completed"},
        )
        return state


def _state(run_id: str) -> AgentState:
    return AgentState(
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        session_id="checkpoint-session",
        user_input="Continue this task.",
        selected_text="Persisted reading context.",
        browser_context={"request_id": 17, "source_kind": "pdf"},
    )


def _runtime(
    service: DirectAnswerService,
    checkpoint_service: AgentCheckpointService,
    conversations: ConversationProbe | None = None,
    *,
    context_provider=None,
    collaboration_adapter=None,
) -> AgentRuntime:
    return AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(
                service,
                conversation_service=conversations,
            ),
            checkpointer=checkpoint_service.checkpointer,
            context_provider=context_provider,
            collaboration_adapter=collaboration_adapter,
        )
    )


def test_context_resolution_resumes_from_initial_graph_checkpoint(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite3"
    run_id = "run-context-interrupted"
    interrupted_context = ContextProviderProbe(interrupt=True)
    first_store = AgentCheckpointService(storage_path=checkpoint_path)
    first_runtime = _runtime(
        DirectAnswerService(),
        first_store,
        context_provider=interrupted_context,
    )

    with pytest.raises(KeyboardInterrupt, match="context interruption"):
        first_runtime.execute(_state(run_id))

    assert interrupted_context.calls == 1
    assert first_runtime.restore_checkpoint(run_id).run_id == run_id
    first_store.close()

    resumed_context = ContextProviderProbe()
    reopened_store = AgentCheckpointService(storage_path=checkpoint_path)
    resumed_runtime = _runtime(
        DirectAnswerService(),
        reopened_store,
        context_provider=resumed_context,
    )

    result = resumed_runtime.execute(_state(run_id), resume=True)

    assert resumed_context.calls == 1
    assert result.browser_context["context_before"] == "restored context"
    reopened_store.close()


def test_multi_agent_stage_resumes_without_repeating_completed_context_node(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite3"
    run_id = "run-collaboration-interrupted"
    initial_context = ContextProviderProbe()
    interrupted_collaboration = CollaborationProbe(interrupt=True)
    first_store = AgentCheckpointService(storage_path=checkpoint_path)
    first_runtime = _runtime(
        DirectAnswerService(),
        first_store,
        context_provider=initial_context,
        collaboration_adapter=interrupted_collaboration,
    )

    with pytest.raises(KeyboardInterrupt, match="collaboration interruption"):
        first_runtime.execute(_state(run_id))

    assert initial_context.calls == 1
    assert interrupted_collaboration.calls == 1
    first_store.close()

    resumed_context = ContextProviderProbe()
    resumed_collaboration = CollaborationProbe()
    reopened_store = AgentCheckpointService(storage_path=checkpoint_path)
    resumed_runtime = _runtime(
        DirectAnswerService(),
        reopened_store,
        context_provider=resumed_context,
        collaboration_adapter=resumed_collaboration,
    )

    result = resumed_runtime.execute(_state(run_id), resume=True)

    assert resumed_context.calls == 0
    assert resumed_collaboration.calls == 1
    assert result.browser_context["context_before"] == "restored context"
    assert result.browser_context["multi_agent_context"] == {"status": "restored"}
    assert AgentEventType.MULTI_AGENT_COMPLETED in {
        event.event_type for event in resumed_runtime.events
    }
    reopened_store.close()


def test_interrupted_graph_resumes_from_last_durable_node_after_reopen(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite3"
    run_id = "run-interrupted"
    first_conversations = ConversationProbe()
    first_store = AgentCheckpointService(storage_path=checkpoint_path)
    first_runtime = _runtime(
        DirectAnswerService(interrupt_route=True),
        first_store,
        first_conversations,
    )

    with pytest.raises(KeyboardInterrupt, match="simulated process interruption"):
        first_runtime.execute(_state(run_id))

    restored_before_reopen = first_runtime.restore_checkpoint(run_id)
    assert restored_before_reopen.conversation.conversation_id == "conversation-checkpoint"
    assert first_conversations.calls == ["begin", "apply"]
    first_store.close()

    resumed_service = DirectAnswerService()
    resumed_conversations = ConversationProbe()
    reopened_store = AgentCheckpointService(storage_path=checkpoint_path)
    resumed_runtime = _runtime(
        resumed_service,
        reopened_store,
        resumed_conversations,
    )

    result = resumed_runtime.execute(_state(run_id), resume=True)

    assert result.run_id == run_id
    assert result.response["output_text"] == "Recovered from the durable checkpoint."
    assert resumed_service.route_calls == 1
    assert resumed_service.run_calls == 1
    assert resumed_conversations.calls == ["complete"]
    assert resumed_runtime.events[0].payload["resumed"] is True
    reopened_store.close()


def test_resuming_completed_checkpoint_is_idempotent_after_reopen(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite3"
    run_id = "run-completed"
    first_service = DirectAnswerService()
    first_store = AgentCheckpointService(storage_path=checkpoint_path)
    first_result = _runtime(first_service, first_store).execute(_state(run_id))

    assert first_result.response["status"] == "completed"
    assert first_service.run_calls == 1
    first_store.close()

    resumed_service = DirectAnswerService()
    reopened_store = AgentCheckpointService(storage_path=checkpoint_path)
    resumed_runtime = _runtime(resumed_service, reopened_store)

    resumed_result = resumed_runtime.execute(_state(run_id), resume=True)

    assert resumed_result.response["output_text"] == first_result.response["output_text"]
    assert resumed_service.route_calls == 0
    assert resumed_service.run_calls == 0
    reopened_store.close()


def test_missing_checkpoint_is_rejected_instead_of_starting_a_new_run(tmp_path) -> None:
    store = AgentCheckpointService(storage_path=tmp_path / "agent-checkpoints.sqlite3")
    runtime = _runtime(DirectAnswerService(), store)

    with pytest.raises(AgentRuntimeError, match="No resumable Agent checkpoint") as exc_info:
        runtime.execute(_state("run-missing"), resume=True)

    assert exc_info.value.stage == "checkpoint"
    assert exc_info.value.fallback_reason == "checkpoint_not_found"
    store.close()


def test_pending_write_tool_is_never_automatically_replayed(tmp_path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoints.sqlite3"
    run_id = "run-pending-write"
    store = AgentCheckpointService(storage_path=checkpoint_path)
    runtime = _runtime(InterruptedWriteService(), store)

    with pytest.raises(KeyboardInterrupt, match="before write result"):
        runtime.execute(_state(run_id))

    with pytest.raises(AgentRuntimeError, match="automatic replay is blocked") as exc_info:
        runtime.restore_checkpoint(run_id)

    assert exc_info.value.fallback_reason == "write_checkpoint_requires_manual_recovery"
    store.close()
