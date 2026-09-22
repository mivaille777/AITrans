from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.exceptions import AgentPauseRequestedError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.knowledge_access_router import KnowledgeAccessRouter


class _PauseAtKnowledgeScope(AgentRunControl):
    def pause_at_boundary(self, node: str) -> None:
        if node == "knowledge_scope":
            self.pause()
        super().pause_at_boundary(node)


class _SemanticCounter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, **_payload):
        self.calls += 1
        return {
            "should_retrieve": False,
            "reason_code": "current_context_sufficient",
            "scope_strategy": "none",
            "confidence": 0.86,
        }


class _GraphService:
    def __init__(self) -> None:
        self.route_calls = 0
        self.run_calls = 0

    def resolve_route(self, *, control=None, **_payload):
        self.route_calls += 1
        return (
            AgentRouteDecision(
                kind="answer",
                source="semantic_router",
                intent="answer",
                user_visible_reason="Answer from the current context.",
            ),
            {"llm_called": False},
        )

    def run(self, *, _resolved_route=None, **_payload):
        self.run_calls += 1
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="answer", user_visible_reason="done"),
            output_text="done",
            provider="fake",
            model="fake",
            request_id=0,
            tool_result=None,
            route=AgentRouteDecision.model_validate(_resolved_route),
        )


def test_checkpoint_after_knowledge_decision_does_not_repeat_semantic_router(
    tmp_path,
) -> None:
    path = tmp_path / "knowledge-graph-checkpoints.sqlite3"
    run_id = "run-knowledge-decision-checkpoint"
    message = "这个方法和另一种方法相比有什么隐含差异？"

    first_semantic = _SemanticCounter()
    first_checkpoint = AgentCheckpointService(storage_path=path)
    first_runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(
                _GraphService(),
                knowledge_access_router=KnowledgeAccessRouter(first_semantic),
            ),
            checkpointer=first_checkpoint.checkpointer,
        )
    )

    with pytest.raises(AgentPauseRequestedError):
        first_runtime.execute(
            AgentState(run_id=run_id, user_input=message),
            control=_PauseAtKnowledgeScope(),
        )

    checkpointed = first_runtime.restore_checkpoint(run_id)
    assert first_semantic.calls == 1
    assert checkpointed.knowledge_decision is not None
    assert checkpointed.knowledge_scope.strategy.value == "none"
    first_checkpoint.close()

    second_semantic = _SemanticCounter()
    second_checkpoint = AgentCheckpointService(storage_path=path)
    second_service = _GraphService()
    second_runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(
                second_service,
                knowledge_access_router=KnowledgeAccessRouter(second_semantic),
            ),
            checkpointer=second_checkpoint.checkpointer,
        )
    )

    result = second_runtime.execute(
        second_runtime.restore_checkpoint(run_id),
        resume=True,
    )

    assert second_semantic.calls == 0
    assert second_service.route_calls == 1
    assert second_service.run_calls == 1
    assert result.knowledge_decision is not None
    assert result.response["output_text"] == "done"
    second_checkpoint.close()
