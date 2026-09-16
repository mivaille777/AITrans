from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.multi_agent.base_agent import AgentResult
from backend.agent_core.multi_agent.context import AgentMemoryAdapter, KnowledgeInjector, SharedAgentContext
from backend.agent_core.multi_agent.orchestration.planner import AgentPlanner
from backend.agent_core.state import AgentState
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge


def test_characterization_f01_keyword_planner_sends_same_task_to_every_selected_role() -> None:
    task = "请总结并翻译这篇论文"

    plan = AgentPlanner().create_plan(task)

    assert [item["agent"] for item in plan] == ["research", "reading", "translation"]
    assert [item["task"] for item in plan] == [task, task, task]


def test_characterization_f03_scope_metadata_does_not_reach_knowledge_runtime() -> None:
    observed: list[tuple[str, int]] = []

    class ScopeBlindRuntime:
        def build_context(self, query: str, top_k: int = 5):
            observed.append((query, top_k))
            return {
                "context": "[workspace-b-private] marker from workspace B",
                "citations": [
                    {
                        "id": "workspace-b-private",
                        "title": "B private node",
                        "source_type": "concept",
                        "score": 0.05,
                    }
                ],
            }

    context = SharedAgentContext(query="unrelated")
    context.runtime.update(
        {
            "workspace_id": "workspace-a",
            "knowledge_document_ids": ["doc-a"],
        }
    )

    KnowledgeInjector(ScopeBlindRuntime()).inject(context.query, context)

    # Characterization of the current P0 gap: the injector passes only query/top_k,
    # so scope metadata cannot constrain the runtime call and B reaches final context.
    assert observed == [("unrelated", 5)]
    assert "workspace-b-private" in context.knowledge_context
    assert context.citations[0]["id"] == "workspace-b-private"


def test_characterization_f04_same_role_result_overwrites_previous_instance() -> None:
    context = SharedAgentContext(query="compare paper A and B")
    first = AgentResult(agent_name="reading", output="paper-a")
    second = AgentResult(agent_name="reading", output="paper-b")

    context.add_result("reading", first)
    context.add_result("reading", second)

    assert list(context.intermediate_results) == ["reading"]
    assert context.intermediate_results["reading"] is second


def test_characterization_f07_bridge_forwards_events_only_after_service_returns() -> None:
    emitted: list[tuple[object, dict[str, object]]] = []

    class FakeService:
        planner = AgentPlanner()

        def run(self, *_args, **_kwargs):
            # No event can reach the consumer while service.run is still active.
            assert emitted == []
            return SimpleNamespace(
                run_id="run-char",
                trace_id="trace-char",
                plan=({"agent": "research", "task": "research"},),
                results=(),
                context=SimpleNamespace(knowledge_context="", citations=[]),
                events=(
                    SimpleNamespace(
                        event_type="supervisor_started",
                        actor="supervisor",
                        status="running",
                        payload={},
                    ),
                ),
                total_duration_ms=1,
            )

    bridge = MultiAgentRuntimeBridge(FakeService())
    state = AgentState(
        session_id="session-char",
        user_input="research task",
        browser_context={"multi_agent_mode": "force"},
    )

    bridge.run_with_events(state, lambda kind, payload: emitted.append((kind, payload)))

    assert len(emitted) == 1
    assert emitted[0][1]["multi_agent_event_type"] == "supervisor_started"


def test_characterization_f09_default_memory_is_lost_when_adapter_is_reconstructed() -> None:
    first = AgentMemoryAdapter()
    first.save({"finding": "persistent-looking but process-local"}, "profile-1")
    assert first.load("profile-1")

    second = AgentMemoryAdapter()

    assert second.load("profile-1") == {}
