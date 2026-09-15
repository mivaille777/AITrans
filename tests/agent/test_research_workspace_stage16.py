from __future__ import annotations

from pathlib import Path

import pytest

from app.research.notes import ResearchNoteStore
from app.research.workspaces import ResearchWorkspaceStore
from backend.agent_core.state import AgentState
from backend.api.agent import _associate_workspace_result, _state_from_run_request
from backend.api.research import delete_research_workspace
from backend.models.agent_tools import AgentRunRequest
from backend.services.research_note_service import ResearchNoteService, research_source_id
from backend.services.research_workspace_service import ResearchWorkspaceService


def _workspace_service(tmp_path: Path) -> ResearchWorkspaceService:
    return ResearchWorkspaceService(
        ResearchWorkspaceStore(storage_path=tmp_path / "workspaces.sqlite3")
    )


def _note_service(
    tmp_path: Path,
    workspace_service: ResearchWorkspaceService,
) -> ResearchNoteService:
    return ResearchNoteService(
        ResearchNoteStore(storage_path=tmp_path / "notes.sqlite3"),
        workspace_service=workspace_service,
    )


def _request(**updates) -> AgentRunRequest:
    payload = {
        "session_id": "stage16-session",
        "user_message": "Compare the evidence in this project.",
        "source_text": "Gaussian-process evidence.",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_title": "Workspace paper",
        "source_kind": "knowledge_document",
        "knowledge_document_ids": ["client-doc-should-be-ignored"],
        "research_source_ids": ["client-source-should-be-ignored"],
    }
    payload.update(updates)
    return AgentRunRequest.model_validate(payload)


def test_workspace_store_persists_metadata_and_member_relationships(tmp_path: Path) -> None:
    service = _workspace_service(tmp_path)
    created = service.create(
        name="GP + LLM PID",
        description="Paper workspace",
        research_goal="Compare statistical localization and semantic refinement.",
    )
    workspace_id = created.workspace.workspace_id

    assert service.attach_document(workspace_id, "doc-a") is True
    assert service.attach_document(workspace_id, "doc-a") is False
    assert service.attach_note(workspace_id, "note-a") is True
    assert service.attach_conversation(workspace_id, "conversation-a") is True

    profile = service.get(workspace_id)
    assert profile is not None
    assert profile.workspace.name == "GP + LLM PID"
    assert profile.document_ids == ("doc-a",)
    assert profile.note_ids == ("note-a",)
    assert profile.conversation_ids == ("conversation-a",)
    assert profile.document_count == 1
    assert profile.note_count == 1
    assert profile.conversation_count == 1

    updated = service.update(
        workspace_id,
        name="GP + LLM PID Paper",
        description="Updated workspace",
        research_goal="Explain why the combined method reduces anchor dependence.",
    )
    assert updated is not None
    assert updated.workspace.name == "GP + LLM PID Paper"
    assert updated.workspace.research_goal.startswith("Explain why")

    assert service.detach_document(workspace_id, "doc-a") is True
    assert service.get(workspace_id).document_ids == ()  # type: ignore[union-attr]


def test_deleting_workspace_preserves_research_note_resource(tmp_path: Path) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace = workspaces.create(name="Persistent project")
    workspace_id = workspace.workspace.workspace_id

    saved = notes.save(
        source_text="Evidence that must survive project deletion.",
        resource_title="Paper A",
        section_heading="Results",
        source_kind="pdf_uia",
        workspace_id=workspace_id,
    )
    note_id = saved.note.note_id

    profile = workspaces.get(workspace_id)
    assert profile is not None
    assert profile.note_ids == (note_id,)

    response = delete_research_workspace(workspace_id, workspaces)
    assert response.deleted is True
    assert response.resources_preserved is True
    assert workspaces.get(workspace_id) is None
    assert notes.get(note_id) is not None
    assert notes.get(note_id).source_text == "Evidence that must survive project deletion."  # type: ignore[union-attr]


def test_saving_note_inside_workspace_auto_associates_note_and_conversation(
    tmp_path: Path,
) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Auto association").workspace.workspace_id

    result = notes.save(
        source_text="Closed-loop evidence.",
        resource_title="Control paper",
        section_heading="Methods",
        source_kind="pdf_uia",
        conversation_id="conversation-42",
        workspace_id=workspace_id,
    )

    profile = workspaces.get(workspace_id)
    assert profile is not None
    assert profile.note_ids == (result.note.note_id,)
    assert profile.conversation_ids == ("conversation-42",)


def test_research_note_search_can_be_narrowed_to_exact_workspace_note_ids(
    tmp_path: Path,
) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    first = notes.save(
        source_text="Gaussian process uncertainty evidence alpha.",
        resource_url="file:///same-paper.pdf",
        resource_title="Same paper",
        section_heading="Methods",
        source_kind="pdf_uia",
    ).note
    second = notes.save(
        source_text="Gaussian process uncertainty evidence beta.",
        resource_url="file:///same-paper.pdf",
        resource_title="Same paper",
        section_heading="Methods",
        source_kind="pdf_uia",
    ).note

    matches = notes.search(
        "Gaussian process uncertainty evidence",
        note_ids=[second.note_id],
        limit=8,
    )

    assert [match.note.note_id for match in matches] == [second.note_id]
    assert first.note_id != second.note_id


def test_agent_workspace_scope_overrides_client_temporary_scope(tmp_path: Path) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Trusted Agent scope").workspace.workspace_id
    workspaces.attach_document(workspace_id, "workspace-doc-a")
    workspaces.attach_document(workspace_id, "workspace-doc-b")
    note = notes.save(
        source_text="Workspace-owned research evidence.",
        resource_url="file:///workspace-paper.pdf",
        resource_title="Workspace paper",
        section_heading="Evidence",
        source_kind="pdf_uia",
        workspace_id=workspace_id,
    ).note

    state = _state_from_run_request(
        _request(workspace_id=workspace_id),
        workspace_service=workspaces,
        research_notes=notes,
    )

    assert state.browser_context["workspace_id"] == workspace_id
    assert state.browser_context["knowledge_document_ids"] == [
        "workspace-doc-a",
        "workspace-doc-b",
    ]
    assert state.browser_context["research_source_ids"] == [research_source_id(note)]
    assert "client-doc-should-be-ignored" not in state.browser_context["knowledge_document_ids"]
    assert "client-source-should-be-ignored" not in state.browser_context["research_source_ids"]


def test_empty_agent_workspace_scope_stays_closed_instead_of_becoming_global(
    tmp_path: Path,
) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)
    workspace_id = workspaces.create(name="Empty trusted scope").workspace.workspace_id

    state = _state_from_run_request(
        _request(workspace_id=workspace_id),
        workspace_service=workspaces,
        research_notes=notes,
    )

    document_scope = state.browser_context["knowledge_document_ids"]
    research_scope = state.browser_context["research_source_ids"]
    assert len(document_scope) == 1
    assert len(research_scope) == 1
    assert document_scope[0].startswith("__workspace_empty_scope__:document:")
    assert research_scope[0].startswith("__workspace_empty_scope__:research:")
    assert "client-doc-should-be-ignored" not in document_scope
    assert "client-source-should-be-ignored" not in research_scope


def test_agent_rejects_missing_workspace_instead_of_falling_back_global(
    tmp_path: Path,
) -> None:
    workspaces = _workspace_service(tmp_path)
    notes = _note_service(tmp_path, workspaces)

    with pytest.raises(ValueError, match="Research workspace not found"):
        _state_from_run_request(
            _request(workspace_id="missing-workspace"),
            workspace_service=workspaces,
            research_notes=notes,
        )


def test_successful_agent_result_is_associated_with_workspace(tmp_path: Path) -> None:
    workspaces = _workspace_service(tmp_path)
    workspace_id = workspaces.create(name="Agent output association").workspace.workspace_id
    request = _request(workspace_id=workspace_id)
    state = AgentState(
        session_id="stage16-session",
        user_input="Save this evidence.",
        selected_text="Evidence",
        browser_context={"conversation_id": "conversation-agent"},
    )
    state.tool_results = [
        {
            "tool_name": "save_research_note",
            "data": {"note_id": "note-agent"},
        }
    ]
    state.sync_contract()

    _associate_workspace_result(request, state, workspaces)
    _associate_workspace_result(request, state, workspaces)

    profile = workspaces.get(workspace_id)
    assert profile is not None
    assert profile.conversation_ids == ("conversation-agent",)
    assert profile.note_ids == ("note-agent",)
