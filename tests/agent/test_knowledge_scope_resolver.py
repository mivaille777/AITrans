from __future__ import annotations

from pathlib import Path

from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.api.agent import _state_from_run_request
from backend.models.agent_tools import AgentRunRequest
from backend.models.knowledge_access import KnowledgeScopeStrategy
from backend.services.knowledge_scope_resolver import (
    KnowledgeScopeResolver,
    empty_workspace_scope_id,
)
from backend.services.research_note_service import ResearchNoteService
from backend.services.research_workspace_service import ResearchWorkspaceService


def test_reading_prefers_attached_document_over_empty_workspace() -> None:
    scope = KnowledgeScopeResolver().resolve(
        context_mode="reading",
        attached_document_id="doc-A",
        workspace_id="workspace-X",
        workspace_document_ids=(),
        research_source_ids=(),
    )

    assert scope.strategy is KnowledgeScopeStrategy.ATTACHED_DOCUMENT
    assert scope.document_ids == ("doc-A",)
    assert scope.workspace_id == ""
    assert scope.allow_global is False


def test_explicit_documents_override_reading_and_research_workspace() -> None:
    scope = KnowledgeScopeResolver().resolve(
        context_mode="research",
        explicit_document_ids=["doc-B"],
        attached_document_id="doc-A",
        workspace_id="workspace-X",
        workspace_document_ids=["doc-C"],
        research_source_ids=["source-C"],
    )

    assert scope.strategy is KnowledgeScopeStrategy.EXPLICIT_DOCUMENTS
    assert scope.document_ids == ("doc-B",)
    assert scope.workspace_id == ""
    assert scope.research_source_ids == ()


def test_research_workspace_is_closed_when_empty() -> None:
    scope = KnowledgeScopeResolver().resolve(
        context_mode="research",
        workspace_id="workspace-X",
        workspace_document_ids=(),
        research_source_ids=(),
    )

    assert scope.strategy is KnowledgeScopeStrategy.RESEARCH_WORKSPACE
    assert scope.document_ids == (
        empty_workspace_scope_id("workspace-X", "document"),
    )
    assert scope.research_source_ids == (
        empty_workspace_scope_id("workspace-X", "research"),
    )
    assert scope.allow_global is False


def test_global_scope_requires_explicit_permission() -> None:
    resolver = KnowledgeScopeResolver()

    restricted = resolver.resolve(context_mode="general")
    global_scope = resolver.resolve(context_mode="general", global_allowed=True)

    assert restricted.strategy is KnowledgeScopeStrategy.NONE
    assert restricted.allow_global is False
    assert global_scope.strategy is KnowledgeScopeStrategy.GLOBAL_KNOWLEDGE
    assert global_scope.allow_global is True


def _services(tmp_path: Path) -> tuple[
    ResearchWorkspaceService,
    ResearchNoteService,
]:
    workspaces = ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )
    notes = ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspaces,
    )
    return workspaces, notes


def test_api_state_resolves_reading_document_without_workspace_leak(tmp_path: Path) -> None:
    workspaces, notes = _services(tmp_path)
    workspace_id = workspaces.create(name="Empty workspace").workspace.workspace_id
    request = AgentRunRequest(
        context_mode="reading",
        session_id="scope-session",
        user_message="基于当前 Reading Context 分析这篇论文的方法。",
        source_text="The selected abstract passage.",
        resource_title="Paper A",
        source_kind="pdf_uia",
        attached_document_id="doc-A",
        workspace_id=workspace_id,
    )

    state = _state_from_run_request(
        request,
        workspace_service=workspaces,
        research_notes=notes,
    )

    assert state.browser_context["knowledge_scope_strategy"] == "attached_document"
    assert state.browser_context["knowledge_document_ids"] == ["doc-A"]
    assert state.browser_context["workspace_id"] == ""
    assert state.browser_context["active_research_workspace_id"] == workspace_id


def test_api_state_keeps_research_workspace_empty_sentinel(tmp_path: Path) -> None:
    workspaces, notes = _services(tmp_path)
    workspace_id = workspaces.create(name="Empty research workspace").workspace.workspace_id
    request = AgentRunRequest(
        context_mode="research",
        session_id="scope-session",
        user_message="比较当前 Research Workspace 中所有论文的方法。",
        source_text="Current paper context.",
        attached_document_id="doc-A",
        workspace_id=workspace_id,
    )

    state = _state_from_run_request(
        request,
        workspace_service=workspaces,
        research_notes=notes,
    )

    assert state.browser_context["knowledge_scope_strategy"] == "research_workspace"
    assert state.browser_context["workspace_id"] == workspace_id
    assert state.browser_context["knowledge_document_ids"] == [
        empty_workspace_scope_id(workspace_id, "document")
    ]
