"""RT-G01/G02/G05: one production root graph and one checkpoint lineage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.agent_tool_registry import AgentToolExecutionResult


class ProductProbe:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.runs = 0

    def resolve_route(self, **_payload):
        return AgentRouteDecision(
            kind=self.kind,
            source="deterministic",
            intent="translate_selection" if self.kind == "tool" else "answer",
            tool_name="translate_selection" if self.kind == "tool" else "",
        ), {"llm_called": False}

    def run(self, *, event_sink=None, **payload):
        self.runs += 1
        if event_sink is not None:
            event_sink("plan_ready", {"action": self.kind})
            if self.kind == "tool":
                event_sink("tool_call", {"name": "translate_selection"})
                event_sink("tool_result", {"tool_name": "translate_selection"})
        tool_result = (
            AgentToolExecutionResult(
                tool_name="translate_selection", output_text="结果", effect="compute",
            ) if self.kind == "tool" else None
        )
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool" if self.kind == "tool" else "answer",
                tool_name="translate_selection" if self.kind == "tool" else "",
            ),
            output_text="结果", provider="probe", model="", request_id=0,
            tool_result=tool_result,
            route=AgentRouteDecision.model_validate(payload["_resolved_route"]),
        )


def test_root_graph_rejects_a_second_runtime_planner():
    graph = RootAgentGraph(ProductAgentRuntimeAdapter(ProductProbe("answer")))
    with pytest.raises(ValueError, match="Root Graph owns planning"):
        AgentRuntime(workflow_adapter=graph, planner=lambda _state: {})


@pytest.mark.parametrize("kind", ["answer", "tool"])
def test_root_graph_owns_direct_route_and_each_node_checkpoint(tmp_path, kind):
    checkpoints = AgentCheckpointService(
        storage_path=tmp_path / "root-checkpoints.sqlite3"
    )
    probe = ProductProbe(kind)
    graph = RootAgentGraph(
        ProductAgentRuntimeAdapter(probe), checkpointer=checkpoints.checkpointer,
    )
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(
        run_id=f"run-root-{kind}", task_id=f"task-root-{kind}",
        trace_id=f"trace-root-{kind}", user_input="Explain", selected_text="Text",
    )

    result = runtime.execute(state)
    history = list(graph.compiled_graph.get_state_history(
        {"configurable": {"thread_id": state.run_id}}
    ))
    scheduled_nodes = [
        snapshot.next[0] for snapshot in reversed(history)
        if snapshot.next and snapshot.next[0] != "__start__"
    ]

    assert result.response["status"] == "completed"
    assert probe.runs == 1
    assert scheduled_nodes == [
        "resolve_context", "prepare_conversation", "run_collaboration",
        "knowledge_access", "knowledge_scope",
        "route_request", "execute_direct", "finalize_conversation",
    ]
    assert all(
        snapshot.config["configurable"]["thread_id"] == state.run_id
        for snapshot in history
    )
    assert runtime.checkpoint_metadata(state.run_id)["checkpoint_id"]
    checkpoints.close()
