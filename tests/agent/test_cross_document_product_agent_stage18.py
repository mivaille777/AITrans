from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.research.memory import (
    ResearchMemoryClaimDraft,
    ResearchMemoryEntityDraft,
    ResearchMemoryExtractionDraft,
    ResearchMemoryRelationDraft,
    ResearchMemoryStore,
)
from app.research.memory_reliability import ResearchMemoryReliabilityStore
from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.models.agent_runtime import AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.cross_document_research_service import CrossDocumentResearchService
from backend.services.product_agent_service import ProductAgentService
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _NoopExtractor:
    def close(self) -> None:
        return None


class _CaptureGroundedSynthesis:
    prompt_id = "stage18-grounded@1"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_verified(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            answer=SimpleNamespace(
                output_text="Grounded cross-document answer.",
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
        raise AssertionError("Stage 18 comparison must use grounded synthesis.")

    def close(self) -> None:
        return None


def _seed(tmp_path: Path):
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
        reliability_store=ResearchMemoryReliabilityStore(
            storage_path=tmp_path / "memory-reliability.sqlite3"
        ),
    )
    workspace_id = workspaces.create(name="Stage 18 Product").workspace.workspace_id
    seeded_notes = []
    for label in ("a", "b"):
        excerpt = "Controller uses Method A"
        note = notes.save(
            source_text=f"{excerpt}. Evidence from paper {label}.",
            resource_url=f"file:///paper-{label}.pdf",
            resource_title=f"Paper {label.upper()}",
            section_heading="Method",
            workspace_id=workspace_id,
        ).note
        seeded_notes.append(note)
        memory.persist_extraction(
            workspace_id=workspace_id,
            note_id=note.note_id,
            extraction=ResearchMemoryExtractionDraft(
                claims=(
                    ResearchMemoryClaimDraft(
                        text="Controller uses Method A.",
                        claim_type="method",
                        confidence=0.95,
                        evidence_excerpt=excerpt,
                    ),
                ),
                entities=(
                    ResearchMemoryEntityDraft(
                        canonical_name="Controller",
                        entity_type="concept",
                    ),
                    ResearchMemoryEntityDraft(
                        canonical_name="Method A",
                        entity_type="method",
                    ),
                ),
                relations=(
                    ResearchMemoryRelationDraft(
                        subject="Controller",
                        predicate="uses",
                        object="Method A",
                        claim_index=0,
                        confidence=0.95,
                    ),
                ),
                extractor_version="stage18-product-test",
                prompt_id="stage18-product-test",
            ),
        )
    cross = CrossDocumentResearchService(
        research_memory_service=memory,
        research_note_service=notes,
    )
    return notes, memory, cross, workspace_id, seeded_notes


def test_cross_document_tool_is_opt_in_capability() -> None:
    registry = AgentToolRegistry(
        research_memory_service=object(),
        research_note_service=object(),
    )

    assert registry.get_tool("search_research_memory") is not None
    assert registry.get_tool("analyze_cross_document_research") is None


def test_product_agent_uses_grounded_pipeline_and_redacts_cross_document_trace(
    tmp_path: Path,
) -> None:
    notes, memory, cross, workspace_id, seeded_notes = _seed(tmp_path)
    registry = AgentToolRegistry(
        research_note_service=notes,
        research_memory_service=memory,
        cross_document_research_service=cross,
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
        intent="analyze_cross_document_research",
        tool_name="analyze_cross_document_research",
        user_visible_reason="Compare structured evidence across papers.",
        arguments={"query": "Controller uses Method A"},
    )

    result = service.run(
        event_sink=lambda event_type, payload: events.append((event_type, dict(payload))),
        _resolved_route=route,
        source_text="",
        user_message="What do the papers agree on about Method A?",
        workspace_id=workspace_id,
        request_id=18,
    )

    assert result.output_text == "Grounded cross-document answer."
    assert len(result.evidence) >= 2
    assert result.citations
    assert {item.source_id for item in result.evidence}.issuperset(
        {note.note_id for note in seeded_notes}
    )
    assert len(grounded.calls) == 1
    assert grounded.calls[0]["evidence"]
    tool_result_events = [payload for name, payload in events if name == "tool_result"]
    assert tool_result_events
    assert tool_result_events[-1]["tool_name"] == "analyze_cross_document_research"
    assert tool_result_events[-1]["data"] == {}
