from __future__ import annotations

from pathlib import Path

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
from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.research_memory import (
    ResearchMemoryAgentTool,
    SearchResearchMemoryArgs,
)
from backend.services.research_memory_service import ResearchMemoryService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


class _NoopExtractor:
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
    revisions = ResearchMemoryReliabilityStore(
        storage_path=tmp_path / "memory-reliability.sqlite3"
    )
    memory = ResearchMemoryService(
        ResearchMemoryStore(storage_path=tmp_path / "memory.sqlite3"),
        research_note_service=notes,
        workspace_service=workspaces,
        extraction_service=_NoopExtractor(),
        reliability_store=revisions,
    )
    return workspaces, notes, memory, revisions


def _relation_draft(*, predicate: str, target: str, excerpt: str):
    return ResearchMemoryExtractionDraft(
        claims=(
            ResearchMemoryClaimDraft(
                text=f"Controller {predicate} {target}.",
                claim_type="definition",
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
                canonical_name=target,
                entity_type="concept",
            ),
        ),
        relations=(
            ResearchMemoryRelationDraft(
                subject="Controller",
                predicate=predicate,
                object=target,
                claim_index=0,
                confidence=0.95,
            ),
        ),
        extractor_version="stage17.3-test",
        prompt_id="stage17.3-test",
    )


def _persist_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    predicate: str,
    target: str,
):
    excerpt = f"Controller {predicate} {target}"
    note = notes.save(
        source_text=f"The paper states that {excerpt} in this configuration.",
        resource_title=f"Paper {target}",
        section_heading="Method",
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=_relation_draft(
            predicate=predicate,
            target=target,
            excerpt=excerpt,
        ),
    )
    return note


def test_persisted_extraction_records_fresh_source_revision(tmp_path: Path) -> None:
    workspaces, notes, memory, revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Fresh").workspace.workspace_id
    note = _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )

    revision = revisions.get_source_revision(
        workspace_id=workspace_id,
        note_id=note.note_id,
    )

    assert revision is not None
    assert revision.source_fingerprint == note.fingerprint
    assert memory.source_status(workspace_id=workspace_id, note_id=note.note_id) == "fresh"


def test_changed_source_revision_becomes_stale_and_is_not_citable(tmp_path: Path) -> None:
    workspaces, notes, memory, revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Stale").workspace.workspace_id
    note = _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )
    revisions.record_source_revision(
        workspace_id=workspace_id,
        note_id=note.note_id,
        source_fingerprint="superseded-source-fingerprint",
    )
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Controller Method A"),
    )

    assert memory.source_status(workspace_id=workspace_id, note_id=note.note_id) == "stale"
    assert result.data is not None
    assert result.data["stale_result_count"] > 0
    assert result.data["grounded_result_count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []
    assert "not eligible for grounded citations" in result.output_text


def test_deleted_source_note_becomes_orphaned_and_is_not_citable(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Orphaned").workspace.workspace_id
    note = _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )
    assert notes.delete(note.note_id) is True
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Controller Method A"),
    )

    assert memory.source_status(workspace_id=workspace_id, note_id=note.note_id) == "orphaned"
    assert result.data is not None
    assert result.data["orphaned_result_count"] > 0
    assert result.data["grounded_result_count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []


def test_detached_workspace_note_is_not_citable(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Detached").workspace.workspace_id
    note = _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )
    assert workspaces.detach_note(workspace_id, note.note_id) is True
    assert notes.get(note.note_id) is not None
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Controller Method A"),
    )

    assert memory.source_status(workspace_id=workspace_id, note_id=note.note_id) == "detached"
    assert result.data is not None
    assert result.data["detached_result_count"] > 0
    assert result.data["grounded_result_count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []
    assert "Workspace-detached" in result.output_text


def test_legacy_extraction_without_revision_remains_usable_but_not_fresh(tmp_path: Path) -> None:
    workspaces, notes, memory, revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Legacy").workspace.workspace_id
    note = _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )
    assert revisions.delete_source_revision(
        workspace_id=workspace_id,
        note_id=note.note_id,
    ) is True
    tool = ResearchMemoryAgentTool(
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.search_research_memory(
        AgentToolInvocationContext(workspace_id=workspace_id),
        SearchResearchMemoryArgs(query="Controller Method A"),
    )

    assert memory.source_status(workspace_id=workspace_id, note_id=note.note_id) == "legacy_unknown"
    assert result.data is not None
    assert result.data["legacy_unknown_result_count"] > 0
    assert result.data["grounded_result_count"] > 0
    assert result.data["evidence"]
    assert result.data["citations"]


def test_single_value_relation_targets_create_conservative_conflict_group(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Conflict").workspace.workspace_id
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method A",
    )
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="defined_as",
        target="Method B",
    )

    conflicts = memory.conflict_groups(workspace_id=workspace_id)
    reliable = memory.search_reliable(
        workspace_id=workspace_id,
        query="Controller defined as",
        limit=20,
    )

    assert len(conflicts) == 1
    assert conflicts[0].predicate == "defined_as"
    assert len(conflicts[0].target_entity_ids) == 2
    assert len(conflicts[0].note_ids) == 2
    assert any(item.reliability.conflicted for item in reliable)
    assert any(
        "conflicting_single_value_relation" in item.reliability.reason_codes
        for item in reliable
    )


def test_multi_value_relation_does_not_create_false_conflict(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Multi value").workspace.workspace_id
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="uses",
        target="Method A",
    )
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="uses",
        target="Method B",
    )

    assert memory.conflict_groups(workspace_id=workspace_id) == ()


def test_taxonomic_is_a_relation_allows_multiple_targets(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_id = workspaces.create(name="Taxonomy").workspace.workspace_id
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="is_a",
        target="Control method",
    )
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        predicate="is_a",
        target="Optimization method",
    )

    assert memory.conflict_groups(workspace_id=workspace_id) == ()


def test_conflicts_are_isolated_by_workspace(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions = _services(tmp_path)
    workspace_a = workspaces.create(name="Workspace A").workspace.workspace_id
    workspace_b = workspaces.create(name="Workspace B").workspace.workspace_id
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_a,
        predicate="defined_as",
        target="Method A",
    )
    _persist_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_b,
        predicate="defined_as",
        target="Method B",
    )

    assert memory.conflict_groups(workspace_id=workspace_a) == ()
    assert memory.conflict_groups(workspace_id=workspace_b) == ()
