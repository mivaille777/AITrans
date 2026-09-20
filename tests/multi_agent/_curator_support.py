from __future__ import annotations

from pathlib import Path

from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.knowledge.suggestion_repository import (
    SqliteKnowledgeRelationSuggestionRepository,
)
from backend.models.agent_artifacts import (
    ClaimRecord,
    DocumentAnalysisArtifact,
    EvidenceRef,
    KnowledgeDraftArtifact,
    KnowledgeItemDraft,
    NoteDraft,
    RelationProposal,
    SourceCoverage,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext
from backend.services.curator_commit_service import CuratorCommitService
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


def curator_stack(tmp_path: Path, *, memory_coordinator=None):
    knowledge_path = tmp_path / "knowledge.sqlite3"
    workspace_service = ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )
    workspace = workspace_service.create(name="Workspace A")
    notes = ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspace_service,
    )
    knowledge = KnowledgeWorkspaceService(SqliteKnowledgeRepository(knowledge_path))
    suggestions = SqliteKnowledgeRelationSuggestionRepository(knowledge_path)
    artifacts = InMemoryArtifactStore()
    service = CuratorCommitService(
        artifact_store=artifacts,
        knowledge_workspace=knowledge,
        suggestion_repository=suggestions,
        research_notes=notes,
        research_workspaces=workspace_service,
        memory_coordinator=memory_coordinator,
        database_path=knowledge_path,
    )
    scope = ScopeContext.issue(
        scope_revision="curator-v1",
        workspace_id=workspace.workspace.workspace_id,
        allowed_document_ids=["paper-a"],
        allowed_item_ids=[],
        source_versions={"paper-a": "v1"},
    )
    return artifacts, knowledge, suggestions, notes, workspace_service, service, scope


def source_artifact(scope: ScopeContext) -> DocumentAnalysisArtifact:
    return DocumentAnalysisArtifact(
        artifact_id="document-curator-a",
        producer_task_id="document-1",
        scope_ref=scope.scope_ref,
        document_id="paper-a",
        contributions=["The paper introduces a bounded graph method."],
        methods=["The bounded graph method uses verified evidence."],
        content={},
        claims=[
            ClaimRecord(
                claim_id="claim-a",
                statement="The bounded graph method uses verified evidence.",
                evidence_ids=["ev-a"],
            )
        ],
        evidence_refs=[
            EvidenceRef(
                evidence_id="ev-a",
                source_id="paper-a",
                source_type="document_chunk",
                source_version="v1",
            )
        ],
        source_coverage=SourceCoverage(complete=True, covered_refs=["paper-a"]),
        verification_status=VerificationStatus.PASSED,
    )


def draft_artifact(
    scope: ScopeContext,
    *,
    artifact_id: str = "knowledge-draft-a",
    notes: list[NoteDraft] | None = None,
    items: list[KnowledgeItemDraft] | None = None,
    proposals: list[RelationProposal] | None = None,
    content: dict | None = None,
) -> KnowledgeDraftArtifact:
    return KnowledgeDraftArtifact(
        artifact_id=artifact_id,
        producer_task_id="curator-1",
        scope_ref=scope.scope_ref,
        workspace_id=scope.workspace_id,
        notes=list(notes or []),
        items=list(items or []),
        relation_proposals=list(proposals or []),
        content=dict(content or {}),
        evidence_refs=source_artifact(scope).evidence_refs,
        verification_status=VerificationStatus.PASSED,
    )
