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
from backend.agent_tools.cross_document_research import (
    AnalyzeCrossDocumentResearchArgs,
    CrossDocumentResearchAgentTool,
    build_cross_document_research_tool_definition,
)
from backend.services.cross_document_research_service import CrossDocumentResearchService
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
    cross = CrossDocumentResearchService(
        research_memory_service=memory,
        research_note_service=notes,
    )
    return workspaces, notes, memory, revisions, cross


def _save_relation(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
    predicate: str,
    target: str,
    suffix: str = "",
):
    excerpt = f"Controller {predicate} {target}"
    note = notes.save(
        source_text=f"{excerpt}. {suffix}".strip(),
        resource_url=resource_url,
        resource_title=resource_title,
        section_heading=f"Method {suffix}".strip(),
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=f"Controller {predicate} {target}.",
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
            extractor_version="stage18-test",
            prompt_id="stage18-test",
        ),
    )
    return note


def _save_claim(
    *,
    notes: ResearchNoteService,
    memory: ResearchMemoryService,
    workspace_id: str,
    resource_url: str,
    resource_title: str,
    claim_text: str,
):
    note = notes.save(
        source_text=f"Source evidence: {claim_text}",
        resource_url=resource_url,
        resource_title=resource_title,
        workspace_id=workspace_id,
    ).note
    memory.persist_extraction(
        workspace_id=workspace_id,
        note_id=note.note_id,
        extraction=ResearchMemoryExtractionDraft(
            claims=(
                ResearchMemoryClaimDraft(
                    text=claim_text,
                    claim_type="result",
                    confidence=0.9,
                    evidence_excerpt=claim_text,
                ),
            ),
            extractor_version="stage18-test",
            prompt_id="stage18-test",
        ),
    )
    return note


def test_exact_claim_agreement_requires_two_distinct_documents(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Agreement").workspace.workspace_id
    claim = "The proposed controller reduced tracking error."
    _save_claim(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        claim_text=claim,
    )
    _save_claim(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-b.pdf",
        resource_title="Paper B",
        claim_text=claim,
    )

    analysis = cross.analyze(workspace_id=workspace_id, query="tracking error")

    assert analysis.document_count == 2
    claim_agreements = [item for item in analysis.agreements if item.kind == "claim"]
    assert len(claim_agreements) == 1
    assert len(claim_agreements[0].document_ids) == 2
    assert len(claim_agreements[0].supports) == 2


def test_two_sections_from_same_document_do_not_create_agreement(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Same paper").workspace.workspace_id
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="uses",
        target="Method A",
        suffix="section-one",
    )
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="uses",
        target="Method A",
        suffix="section-two",
    )

    analysis = cross.analyze(workspace_id=workspace_id, query="Method A")

    assert analysis.document_count == 1
    assert analysis.agreements == []


def test_relation_agreement_aggregates_two_papers(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Relation agreement").workspace.workspace_id
    for label in ("a", "b"):
        _save_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url=f"file:///paper-{label}.pdf",
            resource_title=f"Paper {label.upper()}",
            predicate="uses",
            target="Method A",
            suffix=label,
        )

    analysis = cross.analyze(workspace_id=workspace_id, query="Controller uses Method A")

    relation_agreements = [item for item in analysis.agreements if item.kind == "relation"]
    assert len(relation_agreements) == 1
    assert relation_agreements[0].statement == "Controller uses Method A"
    assert len(relation_agreements[0].document_ids) == 2


def test_cross_document_single_value_conflict_becomes_disagreement(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Disagreement").workspace.workspace_id
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="defined_as",
        target="Method A",
    )
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-b.pdf",
        resource_title="Paper B",
        predicate="defined_as",
        target="Method B",
    )

    analysis = cross.analyze(workspace_id=workspace_id, query="Controller defined")

    assert analysis.disagreement_count == 1
    disagreement = analysis.disagreements[0]
    assert len(disagreement.document_ids) == 2
    assert {item.target_name for item in disagreement.alternatives} == {
        "Method A",
        "Method B",
    }


def test_conflict_inside_one_document_is_not_cross_document_disagreement(tmp_path: Path) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Internal conflict").workspace.workspace_id
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="defined_as",
        target="Method A",
        suffix="section-one",
    )
    _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="defined_as",
        target="Method B",
        suffix="section-two",
    )

    analysis = cross.analyze(workspace_id=workspace_id, query="Controller defined")

    assert memory.conflict_groups(workspace_id=workspace_id)
    assert analysis.document_count == 1
    assert analysis.disagreements == []


def test_stale_support_is_excluded_from_cross_document_agreement(tmp_path: Path) -> None:
    workspaces, notes, memory, revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Stale source").workspace.workspace_id
    fresh = _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-a.pdf",
        resource_title="Paper A",
        predicate="uses",
        target="Method A",
    )
    stale = _save_relation(
        notes=notes,
        memory=memory,
        workspace_id=workspace_id,
        resource_url="file:///paper-b.pdf",
        resource_title="Paper B",
        predicate="uses",
        target="Method A",
    )
    assert fresh.note_id != stale.note_id
    revisions.record_source_revision(
        workspace_id=workspace_id,
        note_id=stale.note_id,
        source_fingerprint="stale-stage18",
    )

    analysis = cross.analyze(workspace_id=workspace_id, query="Method A")

    assert analysis.document_count == 2
    assert analysis.agreements == []
    assert analysis.relation_support_count == 1


def test_agent_tool_exposes_only_query_to_planner_and_returns_grounded_sources(
    tmp_path: Path,
) -> None:
    workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    workspace_id = workspaces.create(name="Agent comparison").workspace.workspace_id
    for label in ("a", "b"):
        _save_relation(
            notes=notes,
            memory=memory,
            workspace_id=workspace_id,
            resource_url=f"file:///paper-{label}.pdf",
            resource_title=f"Paper {label.upper()}",
            predicate="uses",
            target="Method A",
            suffix=label,
        )
    tool = CrossDocumentResearchAgentTool(
        cross_document_service=cross,
        research_memory_service=memory,
        research_note_service=notes,
    )
    definition = build_cross_document_research_tool_definition(tool)

    assert set(definition.spec.input_schema) == {"query"}
    result = tool.analyze_cross_document_research(
        AgentToolInvocationContext(workspace_id=workspace_id),
        AnalyzeCrossDocumentResearchArgs(query="Controller uses Method A"),
    )

    assert result.data is not None
    assert result.data["document_count"] == 2
    assert result.data["agreement_count"] >= 1
    assert result.data["evidence"]
    assert result.data["citations"]
    assert all(
        item["metadata"]["source_verified"] is True
        for item in result.data["evidence"]
    )


def test_agent_tool_requires_active_workspace(tmp_path: Path) -> None:
    _workspaces, notes, memory, _revisions, cross = _services(tmp_path)
    tool = CrossDocumentResearchAgentTool(
        cross_document_service=cross,
        research_memory_service=memory,
        research_note_service=notes,
    )

    result = tool.analyze_cross_document_research(
        AgentToolInvocationContext(),
        AnalyzeCrossDocumentResearchArgs(query="compare methods"),
    )

    assert result.data is not None
    assert result.data["document_count"] == 0
    assert result.data["evidence"] == []
    assert result.data["citations"] == []
