from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_sandbox_approval_service,
    get_workspace_apply_service,
)
from backend.main import create_app
from backend.sandbox.workspace_snapshot import (
    create_workspace_changeset,
    create_workspace_snapshot,
)
from backend.services.filesystem_workspace_service import FilesystemWorkspaceService
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.workspace_apply_service import WorkspaceApplyService


def test_workspace_changeset_api_requires_approval_then_applies_and_audits(
    tmp_path,
) -> None:
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    (selected / "src" / "delete.txt").write_bytes(b"old")
    workspaces = FilesystemWorkspaceService(tmp_path / "workspace-state.sqlite3")
    workspace = workspaces.create(str(selected))
    manifest = workspaces.snapshot(workspace.workspace_id).manifest
    base = create_workspace_snapshot(
        workspace.workspace_id,
        [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size": item["size_bytes"],
                "mode": item["mode"],
            }
            for item in manifest
        ],
    )
    current = create_workspace_snapshot(
        workspace.workspace_id,
        [
            {
                "relative_path": "src/new.txt",
                "sha256": hashlib.sha256(b"new").hexdigest(),
                "size": 3,
                "mode": 0o644,
            }
        ],
    )
    sandbox_id = "sb_" + "d" * 32
    changeset = create_workspace_changeset(base, current, sandbox_id=sandbox_id)
    change_store = tmp_path / "artifacts" / "workspace_changes"
    patch = change_store / sandbox_id / "src" / "new.txt"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"new")
    approvals = SandboxApprovalService()
    service = WorkspaceApplyService(
        workspaces,
        approvals,
        change_store_root=change_store,
        audit_database_path=tmp_path / "workspace-audit.sqlite3",
    )
    app = create_app()
    app.dependency_overrides[get_workspace_apply_service] = lambda: service
    app.dependency_overrides[get_sandbox_approval_service] = lambda: approvals

    with TestClient(app) as client:
        requested = client.post(
            "/api/sandbox/workspaces/changesets/approval",
            json={"changeset": changeset.model_dump(mode="json")},
        )
        approval_id = requested.json()["approval_id"]
        approved = client.post(f"/api/sandbox/approvals/{approval_id}/approve")
        applied = client.post(
            "/api/sandbox/workspaces/changesets/apply",
            json={
                "changeset": changeset.model_dump(mode="json"),
                "approval_id": approval_id,
            },
        )
        audit = client.get("/api/sandbox/workspaces/apply-audit")

    assert requested.status_code == 200
    assert requested.json()["requested_changes"] == [
        {
            "operation": "delete",
            "path": "src/delete.txt",
            "size_before": 3,
            "size_after": None,
        },
        {
            "operation": "create",
            "path": "src/new.txt",
            "size_before": None,
            "size_after": 3,
        },
    ]
    assert approved.status_code == 200
    assert "grant_id" not in approved.json()
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert audit.status_code == 200
    assert audit.json()[0]["status"] == "applied"
    assert (selected / "src" / "new.txt").read_bytes() == b"new"
    assert not (selected / "src" / "delete.txt").exists()
