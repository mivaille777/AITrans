from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.sandbox.workspace_snapshot import (
    create_workspace_changeset,
    create_workspace_snapshot,
)
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.workspace_apply_service import (
    WorkspaceApplyError,
    WorkspaceApplyService,
)

_SANDBOX_ID = "sb_" + "c" * 32


def _approved_workspace_diff(tmp_path: Path):
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    target = selected / "src" / "file.txt"
    target.write_bytes(b"snapshot")
    workspaces = FilesystemWorkspaceService(tmp_path / "workspace-state.sqlite3")
    workspace = workspaces.create(str(selected))
    manifest = workspaces.snapshot(workspace.workspace_id).manifest
    item = manifest[0]
    base = create_workspace_snapshot(
        workspace.workspace_id,
        [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size": item["size_bytes"],
                "mode": item["mode"],
            }
        ],
    )
    current = create_workspace_snapshot(
        workspace.workspace_id,
        [
            {
                "relative_path": "src/file.txt",
                "sha256": hashlib.sha256(b"sandbox").hexdigest(),
                "size": len(b"sandbox"),
                "mode": item["mode"],
            }
        ],
    )
    changeset = create_workspace_changeset(base, current, sandbox_id=_SANDBOX_ID)
    change_store = tmp_path / "artifacts" / "workspace_changes" / _SANDBOX_ID
    patch = change_store / "src" / "file.txt"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"sandbox")
    approvals = SandboxApprovalService()
    service = WorkspaceApplyService(
        workspaces,
        approvals,
        change_store_root=tmp_path / "artifacts" / "workspace_changes",
        audit_database_path=tmp_path / "workspace-audit.sqlite3",
    )
    approval = service.request_approval(changeset)
    approvals.approve(approval.approval_id)
    return selected, service, changeset, approval.approval_id


def test_host_file_changed_after_snapshot_is_not_overwritten(tmp_path: Path) -> None:
    selected, service, changeset, approval_id = _approved_workspace_diff(tmp_path)
    target = selected / "src" / "file.txt"
    target.write_bytes(b"external edit")

    with pytest.raises(WorkspaceApplyError) as conflict:
        service.apply(changeset, approval_id=approval_id)

    assert conflict.value.code == "workspace_conflict"
    assert target.read_bytes() == b"external edit"
    assert service.list_audit()[0].status == "conflict"


def test_symbolic_link_target_is_never_followed(tmp_path: Path) -> None:
    selected, service, changeset, approval_id = _approved_workspace_diff(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"do not overwrite")
    target = selected / "src" / "file.txt"
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("The current Windows environment does not allow symlink creation.")

    with pytest.raises(WorkspaceApplyError) as conflict:
        service.apply(changeset, approval_id=approval_id)

    assert conflict.value.code == "workspace_conflict"
    assert outside.read_bytes() == b"do not overwrite"
