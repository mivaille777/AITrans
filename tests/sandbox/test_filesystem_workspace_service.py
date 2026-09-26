from __future__ import annotations

from pathlib import Path

import pytest

from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionRequest, SandboxExecutionResult
from backend.sandbox.workspace import SandboxWorkspace, SandboxWorkspaceManager
from backend.services.filesystem_workspace_service import (
    FilesystemWorkspaceLimitError,
    FilesystemWorkspaceService,
    FilesystemWorkspaceUnavailableError,
)


class InputReadingRuntime:
    def __init__(self) -> None:
        self.input_text = ""

    def execute_python(
        self,
        request: SandboxExecutionRequest,
        *,
        workspace: SandboxWorkspace,
    ) -> SandboxExecutionResult:
        self.input_text = (workspace.input_dir / "nested" / "data.csv").read_text(
            encoding="utf-8"
        )
        return SandboxExecutionResult(
            sandbox_id=request.sandbox_id,
            status="succeeded",
            exit_code=0,
            stdout="staged",
            duration_ms=1,
        )


def test_workspace_capability_is_opaque_read_only_and_stages_nested_files(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected"
    (selected / "nested").mkdir(parents=True)
    source = selected / "nested" / "data.csv"
    source.write_text("id,value\n1,private\n", encoding="utf-8")
    service = FilesystemWorkspaceService(tmp_path / "state" / "workspaces.sqlite3")

    workspace = service.create(str(selected))
    public_json = workspace.model_dump_json()
    snapshot = service.snapshot(workspace.workspace_id)
    runtime = InputReadingRuntime()
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )
    result = manager.execute_python("print('read input')", input_files=snapshot.input_files)

    assert workspace.status == "active"
    assert workspace.readable is True
    assert workspace.writable is False
    assert str(selected) not in public_json
    assert "display_path" not in workspace.model_dump()
    assert snapshot.manifest[0]["relative_path"] == "nested/data.csv"
    assert runtime.input_text == source.read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8") == "id,value\n1,private\n"
    assert result.status == "succeeded"
    assert service.list()[0].workspace_id == workspace.workspace_id


def test_revoked_and_missing_workspace_states_are_reported(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    service = FilesystemWorkspaceService(tmp_path / "state.sqlite3")
    workspace = service.create(str(selected))

    assert service.revoke(workspace.workspace_id) is True
    assert service.get(workspace.workspace_id).status == "revoked"
    with pytest.raises(FilesystemWorkspaceUnavailableError):
        service.snapshot(workspace.workspace_id)

    active = service.create(str(selected))
    selected.rmdir()
    assert service.get(active.workspace_id).status == "missing"
    with pytest.raises(FilesystemWorkspaceUnavailableError):
        service.snapshot(active.workspace_id)


def test_workspace_snapshot_enforces_file_count_limit(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    for index in range(65):
        (selected / f"{index:02}.txt").write_text("x", encoding="utf-8")
    service = FilesystemWorkspaceService(tmp_path / "state.sqlite3")
    workspace = service.create(str(selected))

    with pytest.raises(FilesystemWorkspaceLimitError):
        service.snapshot(workspace.workspace_id)
