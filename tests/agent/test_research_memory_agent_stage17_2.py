from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
    ResearchMemoryStore,
)
from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.research_memory import (
    ResearchMemoryAgentTool,
    SearchResearchMemoryArgs,
    build_research_memory_tool_definition,
)
from backend.models.agent_runtime import AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.product_agent_service import ProductAgentService
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _NoopExtractor:
    def close(self) -> None:
        return None


class _CaptureGroundedSynthesis:
    prompt_id = "test-grounded@1"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_verified(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            answer=SimpleNamespace(
                output_text="Grounded structured-memory answer.",
                provider="test",
                model="test-grounded",
                request_id=int(kwargs.get("request_id", 0) or 0),
            ),
            verification=None,
            fallback_applied=False,
        )


class _UnusedChatService:
    prompt_id = "unused"

    def send(self, **_kwargs):
        raise AssertionError("Ungrounded chat synthesis must not be used.")

    def close(self) -> None:
        return None


def _services(tmp_path: Path):
    workspaces = ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )
    notes = ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspaces,
    )
    memory = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_NoopExtractor(),
    )
    return workspaces, notes, memory


def _grounded_draft() -> ResearchMemoryExtractionDraft:
    return ResearchMemoryExtractionDraft(
        claims=(
            ResearchMemoryClaimDraft(
                text="Gaussian-process localization narrows the search region.",
                claim_type="method",
                confidence=0.94,
                evidence_excerpt="Gaussian-process localization narrows the search region",
            ),
        ),
        entities=(
            ResearchMemoryEntityDraft(
                canonical_name="Gaussian process",
                entity_type="model",
                aliases=("GP",),
            ),
            ResearchMemoryEntityDraft(
                canonical_name="Search region",
                entity_type="concept",
            ),
        ),
        relations=(
            ResearchMemoryRelationDraft(
                subject="GP",
                predicate="narrows",
                object="Search region",
                claim_index=0,
                confidence=0.91,
            ),
        ),
        extractor_version="stage17.2-test",
        prompt_id="stage17.2-test",
    )


def _seed_grounded_memory(tmp_path: Path):
    workspaces, notes, memory = _services(tmp_path)
    workspace_id = workspaces.create(name="Stage 17.2").workspace.workspace_id
    source_text = (
        "The method uses bounded local refinement. "
        "Gaussian-process localization narrows the search region before refinement."
    )
    note = notes.save(
        source_text=source_text,
        resource_title="Structured Memory Paper",
        section_heading="Method",
        source_kind="pdf_uia",
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=_grounded_draft(),
    )
    return workspaces, notes, memory, workspace_id, note, source_text


def test_planner_can_control_only_structured_memory_query() -> None:
    definition = build_research_memory_tool_definition(
        ResearchMemoryAgentTool(
            research_memory_service=None,
            research_note_service=object(),
        )
    )

    assert set(definition.spec.input_schema) == {"query"}
    assert definition.spec.validate_planner_arguments({"query": "saved GP method"}) == {
        "query": "saved GP method"
    }
    with pytest.raises(ValueError, match="outside its authority"):
        definition.spec.validate_planner_arguments(
            {"query": "x", "workspace_id": "attacker-selected-workspace"}
        )


def test_product_adapter_propagates_workspace_as_trusted_runtime_context() -> None:
    state = AgentState(
        user_input="What did this project establish?",
        browser_context={
            "workspace_id": "workspace-trusted",
            "knowledge_document_ids": ["doc-a"],
        },
    )

    payload = ProductAgentRuntimeAdapter.build_payload(state)

    assert payload["workspace_id"] == "workspace-trusted"
    assert payload["knowledge_document_ids"] == ["doc-a"]


def test_structured_memory_tool_requires_active_workspace(tmp_path: Path) -> None:
    _workspaces, notes, memory = _services(tmp_path)
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(),
        SearchResearchMemoryArgs(query="Gaussian process"),
    )

    assert result.data is not None
    assert result.data["workspace_id"] == ""
    assert result.data["count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []


def test_claim_and_relation_hits_resolve_to_verified_note_evidence(tmp_path: Path) -> None:
    _workspaces, notes, memory, workspace_id, note, source_text = _seed_grounded_memory(
        tmp_path
    )
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id, request_id=17),
        SearchResearchMemoryArgs(query="Gaussian process search region"),
    )

    assert result.data is not None
    assert result.data["count"] > 0
    assert result.data["grounded_result_count"] > 0
    evidence = result.data["evidence"]
    citations = result.data["citations"]
    assert evidence
    assert citations
    first = evidence[0]
    assert first["source_type"] == "research_memory"
    assert first["source_id"] == note.note_id
    assert first["excerpt"] in source_text
    assert first["metadata"]["source_verified"] is True
    assert first["metadata"]["workspace_id"] == workspace_id
    assert any(first["evidence_id"] in citation["evidence_ids"] for citation in citations)


def test_unrelated_entity_without_claim_provenance_is_not_citable(tmp_path: Path) -> None:
    workspaces, notes, memory = _services(tmp_path)
    workspace_id = workspaces.create(name="Entity only").workspace.workspace_id
    note = notes.save(
        source_text="This passage describes a controller architecture.",
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            entities=(
                ResearchMemoryEntityDraft(
                    canonical_name="Controller architecture",
                    entity_type="concept",
                    description="Derived entity without a supporting claim relation.",
                ),
            ),
            extractor_version="stage17.2-test",
            prompt_id="stage17.2-test",
        ),
    )
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Controller architecture"),
    )

    assert result.data is not None
    assert any(item["kind"] == "entity" for item in result.data["results"])
    assert result.data["grounded_result_count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []


def test_entity_connected_to_claim_relation_inherits_source_evidence(tmp_path: Path) -> None:
    _workspaces, notes, memory, workspace_id, _note, _source = _seed_grounded_memory(
        tmp_path
    )
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Gaussian process"),
    )

    assert result.data is not None
    entity_results = [
        item for item in result.data["results"] if item["kind"] == "entity"
    ]
    assert entity_results
    assert any(item["grounded_evidence_ids"] for item in entity_results)
    assert result.data["evidence"]


def test_product_agent_uses_grounded_pipeline_and_redacts_tool_trace_data(
    tmp_path: Path,
) -> None:
    _workspaces, notes, memory, workspace_id, note, _source = _seed_grounded_memory(
        tmp_path
    )
    registry = AgentToolRegistry(
        research_note_service=notes,
        research_memory_service=memory,
    )
    grounded = _CaptureGroundedSynthesis()
    service = ProductAgentService(
        registry=registry,
        chat_service=_UnusedChatService(),
        grounded_synthesis_service=grounded,
    )
    events: list[tuple[str, dict[str, object]]] = []
    route = AgentRouteDecision(
        kind="tool",
        source="planner",
        intent="search_research_memory",
        tool_name="search_research_memory",
        user_visible_reason="Search saved structured research memory.",
        arguments={"query": "Gaussian process search region"},
    )

    result = service.run(
        event_sink=lambda event_type, payload: events.append((event_type, dict(payload))),
        _resolved_route=route,
        source_text="",
        user_message="What did the saved research say about the search region?",
        workspace_id=workspace_id,
        request_id=42,
    )

    assert result.output_text == "Grounded structured-memory answer."
    assert result.evidence
    assert result.citations
    assert result.evidence[0].source_id == note.note_id
    assert len(grounded.calls) == 1
    assert grounded.calls[0]["evidence"]
    tool_result_events = [payload for name, payload in events if name == "tool_result"]
    assert tool_result_events
    assert tool_result_events[-1]["tool_name"] == "search_research_memory"
    assert tool_result_events[-1]["data"] == {}
