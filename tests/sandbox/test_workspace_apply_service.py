from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.workspace_snapshot import (
    WorkspaceChangeSet,
    create_workspace_changeset,
    create_workspace_snapshot,
)
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_debug_service import SandboxDebugService
from backend.services.workspace_apply_service import (
    WorkspaceApplyError,
    WorkspaceApplyService,
)

_SANDBOX_ID = "sb_" + "a" * 32


def _setup(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    debug_service: SandboxDebugService | None = None,
):
    selected = tmp_path / "selected"
    for relative_path, content in files.items():
        path = selected.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    workspaces = FilesystemWorkspaceService(tmp_path / "workspace-state.sqlite3")
    workspace = workspaces.create(str(selected))
    def record_approval(approval, transition: str, grant_id: str) -> None:
        if debug_service is None:
            return
        target = (
            approval.requested_changes[0].path
            if approval.requested_changes
            else approval.target
        )
        sandbox_id = debug_service.record_activity_for_context(
            approval.run_id,
            approval.tool_call_id,
            kind="approval",
            action=f"approval.{transition}",
            target=target,
            decision=approval.status,
            reason=approval.reason,
            permission_action=approval.permission_action,
            policy_rule=approval.permission_action,
            approval_id=approval.approval_id,
            grant_id=grant_id,
        )
        if sandbox_id is not None:
            debug_service.record_stage(
                sandbox_id,
                "approval",
                "running" if transition == "created" else "complete",
                f"Approval {approval.status}.",
            )

    approvals = SandboxApprovalService(
        transition_recorder=record_approval if debug_service is not None else None
    )
    change_store = tmp_path / "artifacts" / "workspace_changes"
    service = WorkspaceApplyService(
        workspaces,
        approvals,
        change_store_root=change_store,
        audit_database_path=tmp_path / "workspace-audit.sqlite3",
        debug_service=debug_service,
    )
    return selected, workspace, workspaces, approvals, service, change_store


class _DebugManager:
    image = "aitrans-python-sandbox:v1"
    policy = DEFAULT_SANDBOX_POLICY


def _make_changeset(
    selected: Path,
    workspace_id: str,
    workspaces: FilesystemWorkspaceService,
    change_store: Path,
    *,
    updates: dict[str, bytes],
    deletes: set[str] = frozenset(),
    sandbox_id: str = _SANDBOX_ID,
) -> WorkspaceChangeSet:
    manifest = workspaces.snapshot(workspace_id).manifest
    base_files = [
        {
            "relative_path": str(item["relative_path"]),
            "sha256": str(item["sha256"]),
            "size": int(item["size_bytes"]),
            "mode": int(item["mode"]),
        }
        for item in manifest
    ]
    base = create_workspace_snapshot(workspace_id, base_files)
    existing_paths = {str(item["relative_path"]) for item in manifest}
    current_files: list[dict[str, object]] = []
    for item in manifest:
        path = str(item["relative_path"])
        if path in deletes:
            continue
        content = updates.get(
            path,
            selected.joinpath(*path.split("/")).read_bytes(),
        )
        current_files.append(
            {
                "relative_path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "mode": int(item["mode"]),
            }
        )
    for path, content in updates.items():
        if path not in existing_paths:
            current_files.append(
                {
                    "relative_path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "mode": 0o644,
                }
            )
    current = create_workspace_snapshot(workspace_id, current_files)
    changeset = create_workspace_changeset(base, current, sandbox_id=sandbox_id)
    for change in changeset.changes:
        if change.operation in {"create", "modify"}:
            target = change_store.joinpath(sandbox_id, *change.path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(updates[change.path])
    return changeset


def _approve(
    service: WorkspaceApplyService, approvals: SandboxApprovalService, changeset
):
    approval = service.request_approval(changeset)
    approvals.approve(approval.approval_id)
    return approval.approval_id


def test_approved_changeset_creates_modifies_and_deletes_atomically(
    tmp_path: Path,
) -> None:
    selected, workspace, workspaces, approvals, service, change_store = _setup(
        tmp_path,
        {
            "src/modify.txt": b"before",
            "src/delete.txt": b"remove",
            "keep.txt": b"unchanged",
        },
    )
    changeset = _make_changeset(
        selected,
        workspace.workspace_id,
        workspaces,
        change_store,
        updates={"src/modify.txt": b"after", "src/create.txt": b"new"},
        deletes={"src/delete.txt"},
    )
    approval = service.request_approval(changeset)
    assert [(item.operation, item.path) for item in approval.requested_changes] == [
        ("create", "src/create.txt"),
        ("delete", "src/delete.txt"),
        ("modify", "src/modify.txt"),
    ]
    approval_id = approval.approval_id
    approvals.approve(approval_id)

    result = service.apply(changeset, approval_id=approval_id)

    assert result.status == "applied"
    assert (selected / "src" / "modify.txt").read_bytes() == b"after"
    assert (selected / "src" / "create.txt").read_bytes() == b"new"
    assert not (selected / "src" / "delete.txt").exists()
    assert (selected / "keep.txt").read_bytes() == b"unchanged"
    assert not (change_store / _SANDBOX_ID).exists()
    audit = service.list_audit()
    assert [item.status for item in audit[:2]] == ["applied", "approval_requested"]
    assert audit[0].changed_paths == (
        "src/create.txt",
        "src/delete.txt",
        "src/modify.txt",
    )

    with pytest.raises(WorkspaceApplyError) as replay:
        service.apply(changeset, approval_id=approval_id)
    assert replay.value.code == "approval_grant_replayed"


def test_workspace_apply_and_approval_transitions_are_traced(tmp_path: Path) -> None:
    debug_service = SandboxDebugService()
    try:
        selected, workspace, workspaces, approvals, service, change_store = _setup(
            tmp_path,
            {"src/file.txt": b"before"},
            debug_service=debug_service,
        )
        sandbox_id, _on_stage = debug_service.begin_agent_run(
            run_id="run-apply-trace",
            tool_call_id="call-apply-trace",
            filesystem_workspace_id=workspace.workspace_id,
            workspace_name=workspace.display_name,
            manager=_DebugManager(),
        )
        changeset = _make_changeset(
            selected,
            workspace.workspace_id,
            workspaces,
            change_store,
            updates={"src/file.txt": b"after"},
            sandbox_id=sandbox_id,
        )

        approval = service.request_approval(changeset)
        approvals.approve(approval.approval_id)
        service.apply(changeset, approval_id=approval.approval_id)

        trace = debug_service.get_run(sandbox_id)
        actions = [activity.action for activity in trace.activities]
        assert "permission.request" in actions
        assert "permission.approval_required" in actions
        assert "approval.created" in actions
        assert "approval.approved" in actions
        assert "approval.consumed" in actions
        assert "filesystem.apply" in actions
        assert trace.stages[-3].key == "apply"
        assert trace.stages[-3].status == "complete"
        assert trace.activities[-1].grant_id
    finally:
        debug_service.close()


def test_apply_rejects_missing_approval_and_wrong_changeset_scope(
    tmp_path: Path,
) -> None:
    selected, workspace, workspaces, approvals, service, change_store = _setup(
        tmp_path, {"src/file.txt": b"before"}
    )
    changeset = _make_changeset(
        selected,
        workspace.workspace_id,
        workspaces,
        change_store,
        updates={"src/file.txt": b"approved"},
    )
    with pytest.raises(WorkspaceApplyError) as missing:
        service.apply(changeset, approval_id="missing")
    assert missing.value.code == "approval_not_found"

    other_changeset = _make_changeset(
        selected,
        workspace.workspace_id,
        workspaces,
        change_store,
        updates={"src/file.txt": b"different"},
        sandbox_id="sb_" + "b" * 32,
    )
    approval_id = _approve(service, approvals, changeset)
    with pytest.raises(WorkspaceApplyError) as wrong_scope:
        service.apply(other_changeset, approval_id=approval_id)
    assert wrong_scope.value.code == "approval_grant_scope_mismatch"
    assert (selected / "src" / "file.txt").read_bytes() == b"before"


def test_failed_atomic_replace_keeps_original_file_intact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected, workspace, workspaces, approvals, service, change_store = _setup(
        tmp_path, {"src/file.txt": b"before"}
    )
    changeset = _make_changeset(
        selected,
        workspace.workspace_id,
        workspaces,
        change_store,
        updates={"src/file.txt": b"after"},
    )
    approval_id = _approve(service, approvals, changeset)

    def fail_replace(*_args, **_kwargs):
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(
        "backend.services.workspace_apply_service.os.replace", fail_replace
    )
    with pytest.raises(WorkspaceApplyError) as failure:
        service.apply(changeset, approval_id=approval_id)

    assert failure.value.code == "workspace_apply_failed"
    assert (selected / "src" / "file.txt").read_bytes() == b"before"
    assert not list((selected / "src").glob(".aitrans-*.partial"))
    assert service.list_audit()[0].status == "failed"
