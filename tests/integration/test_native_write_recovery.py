from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.exceptions import AgentCancelledError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.agent_tools.base import (
    AgentToolModel,
    EmptyToolResultData,
    typed_tool_definition,
)
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.models.agent_runtime import AgentRouteDecision, AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.agent_run_store import AgentRunStore, AgentRunStoreConflictError
from backend.services.agent_tool_execution_service import bind_tool_run_store
from backend.services.agent_tool_registry import AgentToolExecutionResult
from backend.services.product_agent_service import ProductAgentService


class WriteArgs(AgentToolModel):
    user_note: str


class WriteRegistry:
    def __init__(self) -> None:
        self.physical_writes = 0

        def write(_context, arguments):
            self.physical_writes += 1
            return AgentToolExecutionResult(
                tool_name="save_research_note",
                output_text="saved",
                effect="write",
                data={},
            )

        self.definition = typed_tool_definition(
            name="save_research_note",
            title="Save research note",
            description="Save a user requested research note.",
            category="research",
            effect="write",
            requires_reading_context=False,
            requires_confirmation=True,
            args_model=WriteArgs,
            result_model=EmptyToolResultData,
            executor=write,
            retry_policy="never",
        )

    def list_tools(self):
        return (self.definition.spec,)

    def get_tool(self, name):
        return self.definition.spec if name == self.definition.spec.name else None

    def get_definition(self, name):
        return self.definition if name == self.definition.spec.name else None

    def validate_planner_arguments(self, name, arguments):
        if name != self.definition.spec.name:
            raise KeyError(name)
        return self.definition.spec.validate_planner_arguments(arguments)

    def allows_safe_retry(self, name):
        if name != self.definition.spec.name:
            raise KeyError(name)
        return False

    def execute(self, name, **payload):
        if name != self.definition.spec.name:
            raise KeyError(name)
        args = self.definition.parse_args(payload)
        return self.definition.normalize_execution_result(
            self.definition.executor(None, args)
        )


class FakeChatService:
    def send(self, **_kwargs):
        return SimpleNamespace(
            output_text="done",
            provider="test",
            model="test",
            request_id=0,
        )


def _runtime(checkpointer, registry) -> AgentRuntime:
    product = ProductAgentService(registry=registry, chat_service=FakeChatService())
    route = AgentRouteDecision(
        kind="tool",
        source="deterministic",
        intent="save_research_note",
        tool_name="save_research_note",
        user_visible_reason="Save the requested note.",
        arguments={"user_note": "Keep this exact note."},
    )
    product.resolve_route = lambda **_kwargs: (
        route,
        {"duration_ms": 0, "provider": "test", "model": "test", "llm_called": False},
    )
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(product),
        checkpointer=checkpointer,
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )
    return AgentRuntime(workflow_adapter=graph)


def _initial_state(run: AgentRunRecord) -> AgentState:
    return AgentState(
        task_id=run.task_id,
        run_id=run.run_id,
        trace_id=run.trace_id,
        runtime_profile=run.runtime_profile,
        user_input="Save this note",
    )


def _create_run(store: AgentRunStore) -> AgentRunRecord:
    task = AgentTaskRecord(task_id="task-write-recovery", goal="Save a note")
    run = AgentRunRecord(
        task_id=task.task_id,
        run_id="run-write-recovery",
        trace_id="trace-write-recovery",
        runtime_profile=AgentRuntimeProfile.LONG_TASK,
        engine="native",
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
    )
    store.create_task_and_run(task, run, request_payload={"user_message": "Save this note"})
    store.transition_run(
        run.run_id,
        expected_status=AgentRunStatus.QUEUED,
        target_status=AgentRunStatus.RUNNING,
    )
    return run


@pytest.mark.parametrize("approved", [True, False])
def test_native_write_interrupt_survives_restart_and_is_one_shot(tmp_path, approved):
    run_store_path = tmp_path / "runs.sqlite3"
    checkpoint_path = tmp_path / "checkpoints.sqlite3"
    store = AgentRunStore(storage_path=run_store_path)
    run = _create_run(store)
    registry = WriteRegistry()
    checkpoints = AgentCheckpointService(storage_path=checkpoint_path)
    runtime = _runtime(checkpoints.checkpointer, registry)

    pending_state = runtime.execute(
        _initial_state(run),
        event_sink=store.append_event,
    )
    assert pending_state.response["status"] == "confirmation_required"
    assert registry.physical_writes == 0
    required_events = [
        event
        for event in store.list_events(run.run_id)
        if event.event_type.value == "write_confirmation_required"
    ]
    assert len(required_events) == 1
    intent = required_events[0].payload["intent"]

    store.transition_run(
        run.run_id,
        expected_status=AgentRunStatus.RUNNING,
        target_status=AgentRunStatus.WAITING,
    )
    checkpoints.close()
    store.close()

    # Reopening both stores models a process restart while the graph is waiting.
    store = AgentRunStore(storage_path=run_store_path)
    checkpoints = AgentCheckpointService(storage_path=checkpoint_path)
    runtime = _runtime(checkpoints.checkpointer, registry)
    restored = runtime.restore_checkpoint(run.run_id)
    assert store.get_run(run.run_id).status is AgentRunStatus.WAITING

    with pytest.raises(AgentRunStoreConflictError):
        store.confirm_waiting_run(run.run_id, tool_name="different_tool")
    store.confirm_waiting_run(
        run.run_id,
        tool_name="save_research_note",
        approved=approved,
    )
    claimed, recovering = store.claim_next_run(
        lease_owner="stage9-worker", lease_seconds=30
    )
    assert claimed.run_id == run.run_id
    assert recovering is True
    decision = store.consume_write_confirmation(
        run.run_id, lease_owner="stage9-worker"
    )
    assert decision == {**intent, "approved": approved}
    assert store.consume_write_confirmation(
        run.run_id, lease_owner="stage9-worker"
    ) is None
    restored.browser_context = {
        **restored.browser_context,
        "write_confirmation_decision": decision,
    }

    if approved:
        with bind_tool_run_store(store):
            result = runtime.execute(
                restored,
                resume=True,
                event_sink=store.append_event,
            )
        assert result.response["status"] == "completed"
        assert registry.physical_writes == 1
        with store._connect() as connection:
            calls = connection.execute(
                "SELECT status FROM agent_tool_calls WHERE run_id = ?",
                (run.run_id,),
            ).fetchall()
        assert len(calls) == 1
        assert calls[0]["status"] == "succeeded"
    else:
        with pytest.raises(AgentCancelledError):
            runtime.execute(
                restored,
                resume=True,
                event_sink=store.append_event,
            )
        assert registry.physical_writes == 0

    decision_events = [
        event
        for event in store.list_events(run.run_id)
        if event.event_type.value in {"write_confirmed", "write_rejected"}
    ]
    assert len(decision_events) == 1
    assert decision_events[0].payload["approved"] is approved
    checkpoints.close()
    store.close()
