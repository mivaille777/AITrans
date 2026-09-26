from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_react import AgentEvidenceGateAssessment, AgentReActDecision
from backend.models.agent_runtime import AgentEvidenceItem, AgentRouteDecision
from backend.rag.citation_service import build_evidence_citations
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec


SEARCH_TOOL = AgentToolSpec(
    name="search_knowledge_base",
    title="Search knowledge base",
    description="Search indexed local knowledge.",
    category="knowledge",
    effect="read",
    requires_reading_context=False,
    requires_confirmation=False,
    input_schema={"query": {"type": "string", "maxLength": 4000}},
)
READ_CHUNK_TOOL = AgentToolSpec(
    name="read_knowledge_chunk",
    title="Read knowledge chunk",
    description="Read one located knowledge chunk.",
    category="knowledge",
    effect="read",
    requires_reading_context=False,
    requires_confirmation=False,
    input_schema={"chunk_id": {"type": "string", "maxLength": 256}},
)


def _evidence(name: str, *, document_id: str = "doc-A", location: str | None = None):
    return AgentEvidenceItem(
        evidence_id=f"evidence:{name}",
        source_type="knowledge",
        source_id=document_id,
        title="Agentic RAG paper",
        resource_url=f"file:///{document_id}.pdf",
        location=location or f"Section {name}",
        excerpt=f"Evidence {name}.",
        score=0.9,
    )


class _AgenticService:
    def __init__(self, evidence_by_query=None, *, fail=False) -> None:
        self.evidence_by_query = evidence_by_query or {}
        self.fail = fail
        self.queries: list[str] = []
        self.reads: list[str] = []
        self.payloads: list[dict] = []

    def list_tools(self):
        return (SEARCH_TOOL, READ_CHUNK_TOOL)

    def resolve_route(self, **_payload):
        return (
            AgentRouteDecision(
                kind="complex",
                source="semantic_router",
                intent="complex",
            ),
            {"llm_called": True},
        )

    def run(self, *, _resolved_route=None, **payload):
        route = AgentRouteDecision.model_validate(_resolved_route)
        self.payloads.append(dict(payload))
        if self.fail and route.tool_name == SEARCH_TOOL.name:
            raise RuntimeError("retrieval backend unavailable")
        if route.tool_name == SEARCH_TOOL.name:
            query = str(route.arguments.get("query", "") or "")
            self.queries.append(query)
            candidates = tuple(self.evidence_by_query.get(query, ()))
            evidence = ()
            citations = ()
            result = AgentToolExecutionResult(
                tool_name=SEARCH_TOOL.name,
                output_text=("candidates" if candidates else "No matching knowledge found."),
                effect="read",
                request_id=0,
                data={
                    "query": query,
                    "retrieval_strategy": "hybrid",
                    "results": [
                        {
                            "chunk_id": item.evidence_id.removeprefix("evidence:"),
                            "snippet": item.excerpt[:320],
                        }
                        for item in candidates
                    ],
                    "elapsed_ms": 1.0,
                    "fallback_reason": "" if candidates else "no_matching_evidence",
                    "evidence": [],
                    "citations": [],
                },
            )
        else:
            chunk_id = str(route.arguments.get("chunk_id", "") or "")
            self.reads.append(chunk_id)
            evidence = tuple(
                item
                for chunks in self.evidence_by_query.values()
                for item in chunks
                if item.evidence_id == f"evidence:{chunk_id}"
            )
            citations = tuple(build_evidence_citations(evidence))
            result = AgentToolExecutionResult(
                tool_name=READ_CHUNK_TOOL.name,
                output_text="\n\n".join(item.excerpt for item in evidence),
                effect="read",
                request_id=0,
                data={
                    "anchor_chunk_id": chunk_id,
                    "neighbor_radius": 0,
                    "chunks": [
                        {
                            "chunk_id": chunk_id,
                            "document_id": evidence[0].source_id if evidence else "doc-A",
                            "text": evidence[0].excerpt if evidence else "",
                            "chunk_index": 0,
                        }
                    ],
                    "evidence": [item.model_dump(mode="json") for item in evidence],
                    "citations": [item.model_dump(mode="json") for item in citations],
                },
            )
        return SimpleNamespace(
            status="completed",
            output_text=result.output_text,
            provider="fake",
            model="fake",
            request_id=0,
            tool_result=result,
            evidence=evidence,
            citations=citations,
            route=AgentRouteDecision.model_validate(_resolved_route),
        )

    def synthesize_multi_step(self, *, tool_results, **_payload):
        evidence = []
        seen = set()
        for result in tool_results:
            for raw in dict(result.get("data", {}) or {}).get("evidence", ()):
                item = AgentEvidenceItem.model_validate(raw)
                if item.evidence_id not in seen:
                    evidence.append(item)
                    seen.add(item.evidence_id)
        return SimpleNamespace(
            status="completed",
            output_text=(
                "Grounded answer from evidence."
                if evidence
                else "No sufficient evidence was found."
            ),
            provider="fake",
            model="fake",
            request_id=0,
            evidence=tuple(evidence),
            citations=(),
        )


class _Decisions:
    def __init__(self, values: tuple[tuple[str, str], ...]) -> None:
        self.values = values
        self.calls: list[dict] = []

    def decide(self, *, iteration, **kwargs):
        self.calls.append({"iteration": iteration, **kwargs})
        kind, value = self.values[iteration - 1]
        if kind == "search":
            return AgentReActDecision(
                iteration=iteration,
                kind="tool",
                tool_name=SEARCH_TOOL.name,
                arguments={"query": value},
                action_summary="Search for missing evidence.",
            )
        if kind == "read":
            return AgentReActDecision(
                iteration=iteration,
                kind="tool",
                tool_name=READ_CHUNK_TOOL.name,
                arguments={"chunk_id": value},
                action_summary="Read a relevant candidate chunk.",
            )
        return AgentReActDecision(
            iteration=iteration,
            kind="final",
            final_answer=value,
            action_summary="Answer with the available evidence.",
        )


class _AlwaysRetrieveGate:
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
            reason_codes=["test_keep_retrieving"],
        )


def _runtime(service, decisions, *, gate=None):
    return AgentRuntime(
        workflow_adapter=ReadingAgentGraph(
            ProductAgentRuntimeAdapter(service),
            react_decision_service=decisions,
            evidence_gate_service=gate,
        )
    )


def _state(message: str, **context) -> AgentState:
    return AgentState(
        user_input=message,
        selected_text="",
        browser_context={"context_mode": "general", **context},
    )


def test_zero_retrieval_answers_without_search_tool() -> None:
    service = _AgenticService()
    result = _runtime(service, _Decisions((("final", "Direct answer."),))).execute(
        _state("Explain the concept from the current context.")
    )

    assert service.queries == []
    assert result.retrieval_attempt_count == 0
    assert result.response["output_text"] == "Direct answer."


def test_one_retrieval_stops_when_evidence_is_sufficient() -> None:
    query = "find experiment results"
    service = _AgenticService(
        {query: (_evidence("one", location="Results 1"), _evidence("two", location="Results 2"))}
    )
    result = _runtime(
        service,
        _Decisions(
            (
                ("search", query),
                ("read", "one"),
                ("read", "two"),
                ("final", "unused"),
            )
        ),
    ).execute(_state("Find evidence for the experiment."))

    assert service.queries == [query]
    assert service.reads == ["one", "two"]
    assert result.retrieval_attempt_count == 1
    assert result.knowledge_search_count == 1
    assert result.knowledge_read_count == 2
    assert result.evidence_sufficient is True
    assert result.evidence_sufficiency is not None
    assert result.evidence_sufficiency.sufficient is True


def test_second_retrieval_is_allowed_when_first_round_is_insufficient() -> None:
    first = "find method"
    second = "find limitations"
    service = _AgenticService(
        {
            first: (_evidence("method", location="Method"),),
            second: (_evidence("limits", location="Limitations"),),
        }
    )
    decisions = _Decisions(
        (
            ("search", first),
            ("read", "method"),
            ("search", second),
            ("read", "limits"),
            ("final", "unused"),
        )
    )
    result = _runtime(service, decisions).execute(
        _state("Compare the method and its limitations.")
    )

    assert service.queries == [first, second]
    assert service.reads == ["method", "limits"]
    assert len(decisions.calls) == 4
    assert result.retrieval_attempt_count == 2
    assert result.knowledge_search_count == 2
    assert result.knowledge_read_count == 2
    assert result.evidence_sufficient is True


def test_max_retrieval_rounds_stop_without_infinite_loop() -> None:
    queries = ("round one", "round two", "round three")
    service = _AgenticService(
        {query: (_evidence(query),) for query in queries}
    )
    result = _runtime(
        service,
        _Decisions(tuple(("search", query) for query in queries)),
        gate=_AlwaysRetrieveGate(),
    ).execute(
        _state("Keep searching."),
        control=AgentRunControl(
            policy=AgentExecutionPolicy(max_knowledge_searches=2, max_tool_calls=4)
        ),
    )

    assert service.queries == [queries[0], queries[1]]
    assert result.retrieval_attempt_count == 2
    assert result.react.status == "limit_reached"


def test_retrieval_failure_is_observed_and_does_not_fail_the_run() -> None:
    service = _AgenticService(fail=True)
    runtime = _runtime(
        service,
        _Decisions((("search", "unavailable"), ("final", "I cannot verify this."))),
    )
    result = runtime.execute(_state("Verify this claim with evidence."))

    assert result.response["status"] == "completed"
    assert result.response["output_text"] == "I cannot verify this."
    assert result.evidence_sufficient is False
    assert result.react.observations[-1].success is False
    assert any(
        event.event_type == AgentEventType.EVIDENCE_SUFFICIENCY
        and event.payload["reason"] == "retrieval_failed"
        for event in runtime.events
    )


def test_insufficient_evidence_uses_explicit_safe_final_response() -> None:
    service = _AgenticService(fail=True)
    result = _runtime(
        service,
        _Decisions((("search", "unavailable"),)),
    ).execute(
        _state("Verify this claim with evidence."),
        control=AgentRunControl(
            policy=AgentExecutionPolicy(max_knowledge_searches=1, max_tool_calls=2)
        ),
    )

    assert result.response["status"] == "completed"
    assert "sufficient evidence" in result.response["output_text"]
    assert result.evidence_sufficiency is not None
    assert result.evidence_sufficiency.sufficient is False


def test_current_document_retrieval_keeps_attached_document_scope() -> None:
    query = "current paper results"
    service = _AgenticService(
        {query: (_evidence("result", document_id="doc-A", location="Results"),)}
    )
    result = _runtime(
        service,
        _Decisions((("search", query), ("final", "done"))),
    ).execute(
        _state(
            "根据当前论文的完整实验结果判断结论是否成立",
            context_mode="reading",
            attached_document_id="doc-A",
        )
    )

    assert result.knowledge_scope.strategy.value == "attached_document"
    assert result.knowledge_scope.document_ids == ("doc-A",)
    assert service.payloads[0]["knowledge_document_ids"] == ["doc-A"]


def test_cross_document_retrieval_keeps_explicit_document_scope() -> None:
    query = "compare documents"
    service = _AgenticService(
        {query: (_evidence("comparison", document_id="doc-B"),)}
    )
    result = _runtime(
        service,
        _Decisions((("search", query), ("final", "done"))),
    ).execute(
        _state(
            "跨文档比较两篇论文的方法",
            context_mode="research",
            explicit_knowledge_document_ids=["doc-A", "doc-B"],
        )
    )

    assert result.knowledge_scope.strategy.value == "explicit_documents"
    assert result.knowledge_scope.document_ids == ("doc-A", "doc-B")
    assert service.payloads[0]["knowledge_document_ids"] == ["doc-A", "doc-B"]
