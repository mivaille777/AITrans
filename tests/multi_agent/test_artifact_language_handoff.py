from __future__ import annotations

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskStatus
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationRun


class _Orchestrator:
    def __init__(self) -> None:
        self.scope = ScopeContext.issue(
            scope_revision="artifact-language",
            allowed_document_ids=["paper-a"],
        )

    def route(self, user_input, runtime_context, *, mode):
        del user_input, runtime_context, mode
        return OrchestrationRoute(
            lane=OrchestrationLane.SINGLE,
            reason_code="compound-summary-translation",
        )

    def resolve_memory(self, **kwargs):
        del kwargs
        return self.scope, {"snapshot_id": "memory-1", "role_projections": {}}

    def run(self, user_input, **kwargs):
        del user_input, kwargs
        output = {
            "kind": "document_analysis",
            "artifact_id": "analysis-paper-a",
            "version": 2,
            "content_hash": "artifact-hash",
            "content": {
                "reading_card": {
                    "research_questions": ["How does bounded adaptation work?"],
                    "contributions": ["A source-grounded controller."],
                    "methods": ["Constrained optimization."],
                    "datasets": ["Dataset A."],
                    "experiments": ["Accuracy 91.2%."],
                    "limitations": ["Single-dataset evaluation."],
                    "open_questions": ["Cross-domain transfer is unknown."],
                }
            },
        }
        return ResearchOrchestrationRun(
            run_id="run-language",
            trace_id="trace-language",
            route=OrchestrationRoute(
                lane=OrchestrationLane.SINGLE,
                reason_code="compound-summary-translation",
            ),
            scope=self.scope,
            memory_snapshot={"snapshot_id": "memory-1", "role_projections": {}},
            task_plan=None,
            results=(
                TaskResult(
                    task_id="document-1",
                    attempt_id="document-1:1",
                    status=TaskStatus.SUCCEEDED,
                ),
            ),
            outputs={"document-1": output},
            events=(),
            total_duration_ms=1,
            direct_output=output,
            direct_delivery=True,
        )


def test_compound_summary_translation_uses_versioned_artifact_not_raw_paper() -> None:
    state = AgentState(
        run_id="run-language",
        trace_id="trace-language",
        user_input="先总结这篇论文，再把摘要翻译成英文",
        selected_text="FULL RAW PAPER MUST NOT BE TRANSLATED",
        browser_context={"target_language": "en"},
    )
    bridge = MultiAgentRuntimeBridge(orchestrator=_Orchestrator())

    result = bridge.run_with_events(state, lambda *_args: None)
    payload = ProductAgentRuntimeAdapter.build_payload(result)

    assert "FULL RAW PAPER" not in payload["source_text"]
    assert "Research questions: How does bounded adaptation work?" in payload["source_text"]
    assert result.response_state.output_text == ""
    assert result.browser_context["orchestration_direct_delivery"] is False
    assert result.browser_context["derived_language_input_artifact"] == {
        "artifact_id": "analysis-paper-a",
        "version": 2,
        "content_hash": "artifact-hash",
        "kind": "document_analysis",
    }
