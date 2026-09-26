from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent_core.exceptions import AgentToolError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentEvidenceItem,
    AgentRouteDecision,
)
from backend.rag.citation_service import build_evidence_citations
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.grounded_synthesis_service import (
    NO_KNOWLEDGE_EVIDENCE_MESSAGE,
    GroundedSynthesisService,
)
from backend.services.product_agent_service import ProductAgentService

KNOWLEDGE_TOOL = AgentToolSpec(
    name="search_knowledge_base",
    title="Search knowledge base",
    description="Search indexed knowledge.",
    category="knowledge",
    effect="read",
    requires_reading_context=False,
    requires_confirmation=False,
    input_schema={"query": {"type": "string"}},
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
REGULAR_TOOL = AgentToolSpec(
    name="explain_selection",
    title="Explain",
    description="Explain selection.",
    category="reading",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)


def _grounding_data() -> dict:
    evidence = [
        AgentEvidenceItem(
            evidence_id="evidence:chunk-1",
            source_type="knowledge",
            source_id="doc-1",
            title="Control Paper",
            resource_url="file:///control.pdf",
            location="Page 12 · Section 3.4",
            excerpt="The GP constrains the broad search region.",
            score=0.91,
            metadata={"rank": 1},
        )
    ]
    citations = build_evidence_citations(evidence)
    return {
        "query": "How does the GP help?",
        "retrieval_strategy": "hybrid",
        "results": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "snippet": "The GP constrains the broad search region.",
            }
        ],
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "text": "The GP constrains the broad search region.",
            }
        ],
        "elapsed_ms": 5.0,
        "fallback_reason": "",
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "citations": [item.model_dump(mode="json") for item in citations],
    }


class Registry:
    def __init__(self, knowledge_data: dict | None = None) -> None:
        self.knowledge_data = (
            knowledge_data if knowledge_data is not None else _grounding_data()
        )

    def list_tools(self):
        return (KNOWLEDGE_TOOL, READ_CHUNK_TOOL, REGULAR_TOOL)

    def get_tool(self, name: str):
        return next((tool for tool in self.list_tools() if tool.name == name), None)

    def validate_planner_arguments(self, name: str, arguments: dict):
        tool = self.get_tool(name)
        assert tool is not None
        return tool.validate_planner_arguments(arguments)

    def allows_safe_retry(self, _name: str) -> bool:
        return True

    def execute(self, name: str, **payload):
        if name in {"search_knowledge_base", "read_knowledge_chunk"}:
            return AgentToolExecutionResult(
                tool_name=name,
                output_text="Knowledge result",
                effect="read",
                request_id=payload.get("request_id", 0),
                data=self.knowledge_data,
            )
        return AgentToolExecutionResult(
            tool_name=name,
            output_text="Regular tool observation",
            effect="compute",
            request_id=payload.get("request_id", 0),
            data={},
        )


class CapturingChat:
    prompt_id = "agent-synthesis@test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            session_id=kwargs["session_id"],
            user_message=kwargs["user_message"],
            output_text="Grounded answer [1]",
            provider="fake-agent-synthesis",
            model="synthesis-model",
            request_id=kwargs.get("request_id", 0),
        )


def _payload() -> dict:
    return {
        "session_id": "session-grounded",
        "user_message": "How does the GP help?",
        "source_text": "Current reading selection",
        "translated_text": "",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "file:///reading.pdf",
        "resource_title": "Reading Paper",
        "section_heading": "Discussion",
        "context_before": "Before",
        "context_after": "After",
        "source_kind": "pdf_uia",
        "request_id": 31,
    }


def _route(tool_name: str) -> AgentRouteDecision:
    return AgentRouteDecision(
        kind="tool",
        source="planner",
        intent=tool_name,
        tool_name=tool_name,
        arguments=(
            {"query": "How does the GP help?"}
            if tool_name == KNOWLEDGE_TOOL.name
            else {"chunk_id": "chunk-1"}
            if tool_name == READ_CHUNK_TOOL.name
            else {}
        ),
    )


def _service(registry: Registry, chat: CapturingChat) -> ProductAgentService:
    return ProductAgentService(
        registry=registry,  # type: ignore[arg-type]
        chat_service=chat,  # type: ignore[arg-type]
        grounded_synthesis_service=GroundedSynthesisService(chat_service=chat),
    )


def test_evidence_enters_grounded_context_and_citations_are_preserved() -> None:
    chat = CapturingChat()
    service = _service(Registry(), chat)

    result = service.run(_resolved_route=_route(READ_CHUNK_TOOL.name), **_payload())

    assert result.output_text == "Grounded answer [1]"
    assert [item.evidence_id for item in result.evidence] == ["evidence:chunk-1"]
    assert result.citations == (
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence:chunk-1"],
            label="[1]",
        ),
    )
    assert chat.calls[0]["user_message"] == "How does the GP help?"
    assert chat.calls[0]["source_text"] == "Current reading selection"
    assert (
        "Evidence: The GP constrains the broad search region."
        in chat.calls[0]["tool_context"]
    )
    assert "citation-1 => [1] => evidence:chunk-1" in chat.calls[0]["tool_context"]


def test_grounded_synthesis_includes_non_citable_supplemental_context() -> None:
    chat = CapturingChat()
    evidence = [
        AgentEvidenceItem.model_validate(item)
        for item in _grounding_data()["evidence"]
    ]
    citations = build_evidence_citations(evidence)
    grounded = GroundedSynthesisService(chat_service=chat)

    grounded.send_verified(
        evidence=evidence,
        citations=citations,
        context_overrides={
            "evidence:chunk-1": "[Supplemental Section 3.4]\nAdjacent context."
        },
        session_id="session-grounded",
        user_message="How does the GP help?",
    )

    assert "Supplemental Same-Section Context" in chat.calls[0]["tool_context"]
    assert "Adjacent context." in chat.calls[0]["tool_context"]
    assert "not independently citable" in chat.calls[0]["tool_context"]


def test_rag_observability_reuses_agent_trace_and_sanitizes_tool_event() -> None:
    chat = CapturingChat()
    data = _grounding_data()
    data["observability"] = [
        {
            "event_type": "rag_query_started",
            "payload": {"query_id": "rag-1", "retrieval_strategy": "hybrid"},
        },
        {
            "event_type": "rag_query_started",
            "payload": {"query_id": "rag-1", "retrieval_strategy": "hybrid"},
        },
        {
            "event_type": "rag_evidence_selected",
            "payload": {"query_id": "rag-1", "final_count": 1},
        },
    ]
    events: list[tuple[str, dict]] = []

    _service(Registry(data), chat).run(
        _resolved_route=_route(KNOWLEDGE_TOOL.name),
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
        **_payload(),
    )

    event_types = [event_type for event_type, _ in events]
    assert event_types.count("rag_query_started") == 1
    assert event_types.index("tool_call") < event_types.index("rag_query_started")
    assert event_types.index("rag_evidence_selected") < event_types.index("tool_result")
    tool_payload = next(payload for event_type, payload in events if event_type == "tool_result")
    assert tool_payload["data"] == {}
    assert tool_payload["output_chars"] == len("Knowledge result")
    assert tool_payload["candidate_count"] == 1
    assert "The GP constrains" not in repr(tool_payload)


def test_grounding_verification_emits_only_aggregate_runtime_metrics() -> None:
    chat = CapturingChat()
    events: list[tuple[str, dict]] = []

    _service(Registry(), chat).run(
        _resolved_route=_route(READ_CHUNK_TOOL.name),
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
        **_payload(),
    )

    verification = next(
        payload
        for event_type, payload in events
        if event_type == "grounding_verification_evaluated"
    )
    assert verification["passed"] is True
    assert verification["fallback_applied"] is False
    assert verification["claim_count"] == 0
    assert verification["citation_coverage"] == 1.0
    assert verification["support_rate"] == 1.0
    assert verification["reason_codes"] == ["no_verifiable_claims"]
    tool_result = next(
        payload for event_type, payload in events if event_type == "tool_result"
    )
    assert tool_result["tool_name"] == "read_knowledge_chunk"
    assert tool_result["output_chars"] == len("Knowledge result")
    assert tool_result["candidate_count"] == 1
    serialized = repr(verification)
    assert "Grounded answer" not in serialized
    assert "The GP constrains" not in serialized
    assert "Current reading selection" not in serialized


def test_product_adapter_populates_agent_state_evidence_and_citations() -> None:
    chat = CapturingChat()
    adapter = ProductAgentRuntimeAdapter(_service(Registry(), chat))
    state = AgentState(
        session_id="session-grounded",
        user_input="How does the GP help?",
        selected_text="Current reading selection",
        browser_context={"request_id": 31},
    )

    state, _events = adapter.execute_product(
        state,
        resolved_route=_route(READ_CHUNK_TOOL.name),
    )

    assert [item.evidence_id for item in state.evidence] == ["evidence:chunk-1"]
    assert [item.label for item in state.citations] == ["[1]"]


def test_search_result_snippets_never_populate_agent_grounding() -> None:
    chat = CapturingChat()
    adapter = ProductAgentRuntimeAdapter(_service(Registry(), chat))
    state = AgentState(
        session_id="session-search-only",
        user_input="How does the GP help?",
        selected_text="Current reading selection",
        browser_context={"request_id": 31},
    )

    state, _events = adapter.execute_product(
        state,
        resolved_route=_route(KNOWLEDGE_TOOL.name),
    )

    assert state.evidence == []
    assert state.citations == []


def test_no_evidence_policy_does_not_call_synthesis_model() -> None:
    chat = CapturingChat()
    empty = {**_grounding_data(), "evidence": [], "citations": []}
    service = _service(Registry(empty), chat)

    result = service.run(_resolved_route=_route(KNOWLEDGE_TOOL.name), **_payload())

    assert result.output_text == NO_KNOWLEDGE_EVIDENCE_MESSAGE
    assert result.evidence == ()
    assert result.citations == ()
    assert chat.calls == []


def test_invalid_knowledge_citation_is_rejected() -> None:
    chat = CapturingChat()
    invalid = _grounding_data()
    invalid["citations"] = [
        AgentCitationRef(
            citation_id="citation-1",
            evidence_ids=["evidence:unknown"],
            label="[1]",
        ).model_dump(mode="json")
    ]
    service = _service(Registry(invalid), chat)

    with pytest.raises(AgentToolError, match="invalid evidence or citations"):
        service.run(_resolved_route=_route(READ_CHUNK_TOOL.name), **_payload())
    assert chat.calls == []


def test_original_non_rag_tool_synthesis_path_is_unchanged() -> None:
    chat = CapturingChat()
    service = _service(Registry(), chat)

    result = service.run(_resolved_route=_route(REGULAR_TOOL.name), **_payload())

    assert result.output_text == "Grounded answer [1]"
    assert result.evidence == ()
    assert result.citations == ()
    assert chat.calls[0]["tool_name"] == REGULAR_TOOL.name
    assert "Regular tool observation" in chat.calls[0]["tool_context"]


def test_existing_tool_only_route_still_skips_synthesis() -> None:
    chat = CapturingChat()
    service = _service(Registry(), chat)

    result = service.run(
        _resolved_route=_route(REGULAR_TOOL.name),
        _skip_synthesis=True,
        **_payload(),
    )

    assert result.output_text == "Regular tool observation"
    assert chat.calls == []
