from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import (
    AgentEvidenceGateAssessment,
    AgentReActDecision,
)
from backend.models.agent_runtime import AgentEvidenceItem, AgentRouteDecision
from backend.rag.citation_service import build_evidence_citations
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.agent_trace_store_service import AgentTraceStoreService


KNOWLEDGE_TOOL = AgentToolSpec(
    name="search_knowledge_base",
    title="Search knowledge base",
    description="Search indexed local knowledge.",
    category="knowledge",
    effect="read",
    requires_reading_context=False,
    requires_confirmation=False,
    input_schema={"query": {"type": "string", "maxLength": 4000}},
)


def _evidence(chunk_id: str, excerpt: str) -> AgentEvidenceItem:
    return AgentEvidenceItem(
        evidence_id=f"evidence:{chunk_id}",
        source_type="knowledge",
        source_id="doc-agentic-rag",
        title="Agentic RAG Paper",
        resource_url="file:///agentic-rag.pdf",
        location=f"Section {chunk_id}",
        excerpt=excerpt,
        score=0.9,
        metadata={"rank": 1},
    )


class ComplexKnowledgeService:
    def __init__(self, evidence_by_query: dict[str, tuple[AgentEvidenceItem, ...]]) -> None:
        self.evidence_by_query = evidence_by_query
        self.executed_queries: list[str] = []
        self.synthesis_calls = 0
        self.synthesis_tool_results: list[dict] = []

    def list_tools(self):
        return (KNOWLEDGE_TOOL,)

    def resolve_route(self, *, control=None, **_payload):
        return (
            AgentRouteDecision(
                kind="complex",
                source="semantic_router",
                intent="complex",
                user_visible_reason="Use evidence-driven retrieval.",
            ),
            {
                "duration_ms": 1,
                "provider": "fake-router",
                "model": "fake-router-model",
                "prompt_id": "router@test",
                "llm_called": True,
            },
        )

    def run(self, *, event_sink=None, **payload):
        route = AgentRouteDecision.model_validate(payload["_resolved_route"])
        query = str(route.arguments.get("query", "") or "")
        self.executed_queries.append(query)
        evidence = tuple(self.evidence_by_query.get(query, ()))
        citations = tuple(build_evidence_citations(evidence))
        data = {
            "query": query,
            "retrieval_strategy": "hybrid",
            "results": [
                {"chunk_id": item.evidence_id.removeprefix("evidence:")}
                for item in evidence
            ],
            "elapsed_ms": 2.0,
            "fallback_reason": "" if evidence else "no_matching_evidence",
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "citations": [item.model_dump(mode="json") for item in citations],
        }
        result = AgentToolExecutionResult(
            tool_name=KNOWLEDGE_TOOL.name,
            output_text=(
                "Knowledge evidence found."
                if evidence
                else "No matching knowledge found."
            ),
            effect="read",
            request_id=max(0, int(payload.get("request_id", 0) or 0)),
            data=data,
        )
        if event_sink is not None:
            event_sink(
                "tool_call",
                {
                    "name": KNOWLEDGE_TOOL.name,
                    "effect": "read",
                    "requires_confirmation": False,
                    "request_id": result.request_id,
                },
            )
            event_sink(
                "tool_result",
                {
                    "tool_name": KNOWLEDGE_TOOL.name,
                    "effect": "read",
                    "request_id": result.request_id,
                    "data": {},
                },
            )
        return SimpleNamespace(
            status="completed",
            request_id=result.request_id,
            tool_result=result,
            evidence=evidence,
            citations=citations,
        )

    def synthesize_multi_step(self, *, tool_results, event_sink=None, **payload):
        self.synthesis_calls += 1
        self.synthesis_tool_results = [dict(item) for item in tool_results]
        combined: list[AgentEvidenceItem] = []
        seen: set[str] = set()
        for item in self.synthesis_tool_results:
            data = dict(item.get("data", {}) or {})
            for raw in data.get("evidence", []):
                evidence = AgentEvidenceItem.model_validate(raw)
                if evidence.evidence_id not in seen:
                    combined.append(evidence)
                    seen.add(evidence.evidence_id)
        citations = tuple(build_evidence_citations(combined))
        if event_sink is not None:
            event_sink(
                "synthesis_ready",
                {
                    "provider": "fake-grounded",
                    "model": "fake-grounded-model",
                    "request_id": max(0, int(payload.get("request_id", 0) or 0)),
                    "grounded": bool(combined),
                    "evidence_count": len(combined),
                    "citation_count": len(citations),
                },
            )
        return SimpleNamespace(
            status="completed",
            output_text="Grounded answer from accumulated retrieval evidence.",
            provider="fake-grounded",
            model="fake-grounded-model",
            request_id=max(0, int(payload.get("request_id", 0) or 0)),
            evidence=tuple(combined),
            citations=citations,
        )


class SequenceDecisionService:
    provider_name = "fake-react"
    model = "fake-react-model"
    prompt_id = "agent.react_decision@agentic-rag-test"

    def __init__(self, decisions: tuple[tuple[str, str], ...]) -> None:
        self.decisions = decisions
        self.calls: list[dict] = []

    def decide(self, *, iteration, **kwargs):
        self.calls.append({"iteration": iteration, **kwargs})
        kind, value = self.decisions[iteration - 1]
        if kind == "search":
            return AgentReActDecision(
                iteration=iteration,
                kind="tool",
                tool_name=KNOWLEDGE_TOOL.name,
                arguments={"query": value},
                action_summary="Search for the missing evidence.",
            )
        return AgentReActDecision(
            iteration=iteration,
            kind="final",
            action_summary="Answer from the accumulated evidence.",
            final_answer=value,
        )


class AlwaysRetrieveGate:
    """Test-only gate that keeps retrieval open so budget guards can be isolated."""

    def assess(self, *, evidence, latest_retrieval, search_count, remaining_searches):
        return AgentEvidenceGateAssessment(
            action="retrieve",
            coverage_score=0.0,
            diversity_score=0.0,
            novelty_score=0.0,
            quality_score=0.0,
            evidence_count=len(evidence),
            unique_source_count=0,
            unique_location_count=0,
            novel_evidence_count=min(latest_retrieval.novel_evidence_count, len(evidence)),
            search_count=search_count,
            remaining_searches=remaining_searches,
            retrieval_fallback=False,
            reason_codes=["test_keep_retrieving"],
        )


def _state() -> AgentState:
    return AgentState(
        session_id="agentic-rag",
        user_input="Compare GP global search with LLM local refinement using evidence.",
        selected_text="",
        browser_context={"request_id": 88, "source_kind": "pdf"},
    )


def _runtime(
    service: ComplexKnowledgeService,
    decision_service: SequenceDecisionService,
    *,
    evidence_gate_service=None,
) -> AgentRuntime:
    return AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=decision_service,
            evidence_gate_service=evidence_gate_service,
        )
    )


def test_agentic_rag_reformulates_query_and_gate_stops_when_evidence_is_sufficient() -> None:
    first_query = "Gaussian process global search exploration uncertainty"
    second_query = "LLM local refinement bounded candidate mechanism"
    service = ComplexKnowledgeService(
        {
            first_query: (_evidence("gp", "The GP performs broad statistical search."),),
            second_query: (_evidence("llm", "The LLM performs bounded local refinement."),),
        }
    )
    decisions = SequenceDecisionService(
        (
            ("search", first_query),
            ("search", second_query),
            ("final", "This third LLM decision should not be called."),
        )
    )
    runtime = _runtime(service, decisions)

    result = runtime.execute(_state())

    assert service.executed_queries == [first_query, second_query]
    assert service.synthesis_calls == 1
    assert len(decisions.calls) == 2
    assert result.react.status == "completed"
    assert len(result.react.observations) == 2
    first = result.react.observations[0].retrieval
    second = result.react.observations[1].retrieval
    assert first is not None and second is not None
    assert first.query == first_query
    assert second.query == second_query
    assert first.novel_evidence_count == 1
    assert second.novel_evidence_count == 1
    assert first.gate is not None and first.gate.action == "refine"
    assert second.gate is not None and second.gate.action == "stop"
    assert second.gate.evidence_count == 2
    assert "evidence_sufficient" in second.gate.reason_codes
    assert decisions.calls[1]["observations"][0].retrieval.query == first_query
    assert decisions.calls[1]["remaining_knowledge_searches"] == 2
    assert {item.evidence_id for item in result.evidence} == {
        "evidence:gp",
        "evidence:llm",
    }
    gate_events = [
        event
        for event in runtime.events
        if event.event_type == AgentEventType.EVIDENCE_GATE_EVALUATED
    ]
    assert [event.payload["action"] for event in gate_events] == ["refine", "stop"]
    assert gate_events[-1].payload["evidence_count"] == 2


def test_agentic_rag_gate_stops_search_that_adds_no_new_evidence() -> None:
    first_query = "GP search behavior"
    second_query = "GP statistical exploration behavior"
    same = _evidence("gp", "The GP performs broad statistical search.")
    service = ComplexKnowledgeService(
        {
            first_query: (same,),
            second_query: (same,),
        }
    )
    decisions = SequenceDecisionService(
        (
            ("search", first_query),
            ("search", second_query),
            ("final", "This should be bypassed by the gate."),
        )
    )

    result = _runtime(service, decisions).execute(_state())

    assert len(decisions.calls) == 2
    second = result.react.observations[1].retrieval
    assert second is not None and second.gate is not None
    assert second.evidence_count == 1
    assert second.novel_evidence_count == 0
    assert second.gate.action == "stop"
    assert "no_novel_evidence_after_refinement" in second.gate.reason_codes


def test_agentic_rag_search_budget_still_blocks_third_retrieval() -> None:
    queries = (
        "first missing concept",
        "second missing concept",
        "third missing concept",
    )
    service = ComplexKnowledgeService(
        {
            queries[0]: (_evidence("one", "First evidence."),),
            queries[1]: (_evidence("two", "Second evidence."),),
            queries[2]: (_evidence("three", "Third evidence."),),
        }
    )
    decisions = SequenceDecisionService(tuple(("search", query) for query in queries))
    runtime = _runtime(
        service,
        decisions,
        evidence_gate_service=AlwaysRetrieveGate(),
    )
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            max_tool_calls=4,
            max_react_iterations=6,
            max_knowledge_searches=2,
        )
    )

    result = runtime.execute(_state(), control=control)

    assert service.executed_queries == [queries[0], queries[1]]
    assert service.synthesis_calls == 1
    assert result.react.status == "limit_reached"
    assert len(result.react.decisions) == 3
    assert len(result.react.observations) == 2
    limit = next(
        event
        for event in runtime.events
        if event.event_type == AgentEventType.REACT_LIMIT_REACHED
        and event.payload.get("reason") == "knowledge_search_budget_exhausted"
    )
    assert limit.payload["knowledge_search_count"] == 2


def test_agentic_rag_trace_persists_gate_metrics_without_raw_query(tmp_path) -> None:
    private_query = "PRIVATE exact research query about GP anchors"
    service = ComplexKnowledgeService(
        {private_query: (_evidence("private", "PRIVATE retrieved excerpt."),)}
    )
    decisions = SequenceDecisionService(
        (
            ("search", private_query),
            ("final", "Answer from evidence."),
        )
    )
    store = AgentTraceStoreService(storage_path=tmp_path / "agent.sqlite3")
    runtime = AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=decisions,
        ),
        run_recorder=store.record,
    )

    result = runtime.execute(_state())
    persisted = store.list_events(result.run_id)
    serialized = repr(tuple(event.payload for event in persisted))

    assert private_query not in serialized
    assert "PRIVATE retrieved excerpt." not in serialized
    observation_payload = next(
        event.payload
        for event in persisted
        if event.event_type == "observation_ready"
        and event.payload.get("tool_name") == KNOWLEDGE_TOOL.name
    )
    assert observation_payload["query_fingerprint"]
    assert observation_payload["novel_evidence_count"] == 1
    assert observation_payload["knowledge_search_count"] == 1
    assert observation_payload["gate_action"] == "refine"
    gate_payload = next(
        event.payload
        for event in persisted
        if event.event_type == "evidence_gate_evaluated"
    )
    assert gate_payload["action"] == "refine"
    assert gate_payload["evidence_count"] == 1
    assert "insufficient_evidence_count" in gate_payload["reason_codes"]
