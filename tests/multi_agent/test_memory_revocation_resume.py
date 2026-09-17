import pytest

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.repository import SQLiteMemoryRepository
from backend.models.agent_artifacts import KnowledgeItemDraft, ManuscriptSectionArtifact
from backend.models.agent_tasks import ScopeContext
from backend.models.memory import MemoryKind
from backend.services.curator_commit_service import CuratorCommitError
from backend.services.writing_project_service import (
    WritingProjectError,
    WritingProjectService,
)
from tests.multi_agent._curator_support import curator_stack, draft_artifact


def test_resumed_run_keeps_frozen_version_but_revocation_removes_body(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    item = coordinator.remember(
        operation_id="remember-v1",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.RESEARCH_DECISION,
        content="Use protocol version one.",
        source_ref="user:decision",
    )
    scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="resume",
    )
    first = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="stable-run"
    )
    coordinator.remember(
        operation_id="remember-v2",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.RESEARCH_DECISION,
        content="Use protocol version two.",
        source_ref="user:decision-update",
        item_id=item.item_id,
        expected_version=1,
    )
    resumed = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="stable-run"
    )
    new_run = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="new-run"
    )

    assert first["snapshot_id"] == resumed["snapshot_id"]
    assert "version one" in str(resumed)
    assert "version two" not in str(resumed)
    assert "version two" in str(new_run)

    coordinator.forget(profile_id="profile-a", item_id=item.item_id, expected_version=2)
    invalidated = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="stable-run"
    )
    assert invalidated["status"] == "invalidated"
    assert item.item_id in invalidated["invalidated_item_ids"]
    assert "version one" not in str(invalidated["role_projections"])


def test_distinct_runs_get_distinct_snapshot_ids_for_identical_memory(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    coordinator = MemoryCoordinator(repository)
    scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="same-scope",
    )

    first = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="run-a"
    )
    second = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="run-b"
    )

    assert first["snapshot_id"] != second["snapshot_id"]
    assert (
        coordinator.load_snapshot(
            profile_id="profile-a", scope=scope, run_id="run-a"
        )["snapshot_id"]
        == first["snapshot_id"]
    )


def test_disabled_or_deleted_memory_cannot_reappear_from_old_snapshot(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    coordinator = MemoryCoordinator(repository)
    item = coordinator.remember(
        operation_id="remember",
        profile_id="profile-a",
        kind=MemoryKind.TERMINOLOGY,
        content="SECRET-TERM",
        source_ref="user:term",
    )
    scope = ScopeContext.issue(profile_id="profile-a", scope_revision="global")
    coordinator.load_snapshot(profile_id="profile-a", scope=scope, run_id="run")
    coordinator.forget(profile_id="profile-a", item_id=item.item_id, expected_version=1)
    reopened = MemoryCoordinator(SQLiteMemoryRepository(repository.database_path))
    packet = reopened.load_snapshot(profile_id="profile-a", scope=scope, run_id="run")
    assert "SECRET-TERM" not in str(packet["role_projections"])


def test_workspace_membership_revision_invalidates_frozen_snapshot(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    coordinator.remember(
        operation_id="workspace-memory",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.RESEARCH_DECISION,
        content="MEMBER-SCOPED-CONTENT",
        source_ref="workspace:decision",
    )
    original_scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="members-v1",
        allowed_document_ids=["paper-a"],
    )
    coordinator.load_snapshot(
        profile_id="profile-a", scope=original_scope, run_id="membership-run"
    )
    changed_scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="members-v2",
        allowed_document_ids=[],
    )

    packet = coordinator.load_snapshot(
        profile_id="profile-a", scope=changed_scope, run_id="membership-run"
    )

    assert packet["status"] == "invalidated"
    assert packet["reason_code"] == "snapshot_scope_changed"
    assert "MEMBER-SCOPED-CONTENT" not in str(packet)


def test_curator_commit_revalidates_memory_deletion_before_business_write(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    artifacts, knowledge, _, _, _, service, scope = curator_stack(
        tmp_path, memory_coordinator=coordinator
    )
    memory = coordinator.remember(
        operation_id="curator-preference",
        profile_id="profile-a",
        workspace_id=scope.workspace_id,
        kind=MemoryKind.CURATION_PREFERENCE,
        content="Prefer concise cards.",
        source_ref="user:curator-preference",
    )
    artifact = artifacts.put(
        draft_artifact(
            scope,
            items=[
                KnowledgeItemDraft(
                    draft_id="item-1",
                    item_type="insight",
                    title="One",
                    source_ids=["paper-a"],
                )
            ],
            content={"memory_references": [memory.model_dump(mode="json")]},
        )
    )
    coordinator.forget(
        profile_id="profile-a", item_id=memory.item_id, expected_version=1
    )

    with pytest.raises(CuratorCommitError, match="deleted or disabled"):
        service.apply(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.version,
            operation_id="commit-after-delete",
            scope=scope,
        )

    assert knowledge.list_items() == []


def test_writer_save_revalidates_memory_deletion_before_business_write(tmp_path):
    coordinator = MemoryCoordinator(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    memory = coordinator.remember(
        operation_id="writer-style",
        profile_id="profile-a",
        workspace_id="workspace-a",
        kind=MemoryKind.WRITING_STYLE,
        content="Use a concise style.",
        source_ref="user:writer-style",
    )
    scope = ScopeContext.issue(
        profile_id="profile-a",
        workspace_id="workspace-a",
        scope_revision="writer-memory",
    )
    snapshot = coordinator.load_snapshot(
        profile_id="profile-a", scope=scope, run_id="writer-run"
    )
    artifacts = InMemoryArtifactStore()
    section = artifacts.put(
        ManuscriptSectionArtifact(
            artifact_id="writer-section",
            producer_task_id="writer-1",
            scope_ref=scope.scope_ref,
            section_id="discussion",
            title="Discussion",
            markdown="A concise paragraph.",
            paragraph_ids=["discussion:p1"],
            claim_source_map={"discussion:p1": []},
            content={
                "memory_snapshot_ref": snapshot["snapshot_id"],
                "memory_references": snapshot["references"],
            },
        )
    )
    writing = WritingProjectService(
        artifact_store=artifacts,
        database_path=tmp_path / "writing.sqlite3",
        memory_coordinator=coordinator,
    )
    project = writing.create(workspace_id="workspace-a", title="Paper")
    coordinator.forget(
        profile_id="profile-a", item_id=memory.item_id, expected_version=1
    )

    with pytest.raises(WritingProjectError, match="deleted or disabled"):
        writing.save_section(
            project.project_id,
            artifact_id=section.artifact_id,
            artifact_version=section.version,
            expected_version=0,
        )

    assert writing.get(project.project_id).sections == []
