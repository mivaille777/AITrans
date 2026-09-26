from __future__ import annotations

import hashlib
import stat

import pytest
from pydantic import ValidationError

from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.workspace import SandboxInputFile, SandboxWorkspaceManager
from backend.sandbox.workspace_snapshot import (
    WorkspaceChange,
    WorkspaceSnapshotError,
    create_workspace_changeset,
    create_workspace_snapshot,
    snapshot_directory,
)


def _file(path: str, content: bytes, mode: int = 0o644) -> dict[str, object]:
    return {
        "relative_path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "mode": mode,
    }


def test_workspace_snapshot_hash_covers_content_path_and_mode(tmp_path) -> None:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('one')", encoding="utf-8")
    (root / "README.md").write_text("project", encoding="utf-8")

    first = snapshot_directory(
        root,
        "fsw_project",
        modes={"src/main.py": 0o640, "README.md": 0o644},
    )
    reordered = snapshot_directory(
        root,
        "fsw_project",
        modes={"README.md": 0o644, "src/main.py": 0o640},
    )
    changed_mode = snapshot_directory(
        root,
        "fsw_project",
        modes={"src/main.py": 0o600, "README.md": 0o644},
    )

    assert first.snapshot_hash == reordered.snapshot_hash
    assert first.snapshot_hash != changed_mode.snapshot_hash
    assert [item.relative_path for item in first.files] == [
        "README.md",
        "src/main.py",
    ]
    assert first.files[1].sha256
    assert first.files[1].size == len("print('one')")
    assert first.files[1].mode == 0o640


def test_snapshot_rejects_symbolic_links(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("The current Windows environment does not allow symlink creation.")

    with pytest.raises(WorkspaceSnapshotError, match="symbolic link"):
        snapshot_directory(root, "fsw_project")


def test_read_only_input_is_copied_to_an_editable_workspace(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    manager = SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes",
        artifact_root=tmp_path / "artifacts",
    )
    workspace = manager.create("sb_" + "a" * 32)
    item = SandboxInputFile(
        file_id="source-1",
        display_name="source.txt",
        source_path=source,
        relative_path="src/source.txt",
        expected_mode=0o640,
    )
    try:
        staged = manager.stage_input(workspace, item)
        manager.copy_inputs_to_workspace(workspace, (item,))
        editable = workspace.workspace_dir / "src" / "source.txt"

        assert staged.read_text(encoding="utf-8") == "original"
        assert stat.S_IMODE(staged.stat().st_mode) & 0o222 == 0
        assert editable.read_text(encoding="utf-8") == "original"
        assert stat.S_IMODE(editable.stat().st_mode) & 0o222 != 0
        assert source.read_text(encoding="utf-8") == "original"
    finally:
        manager.cleanup(workspace)


def test_changeset_reports_create_modify_and_delete() -> None:
    base = create_workspace_snapshot(
        "fsw_project",
        [
            _file("keep.txt", b"keep"),
            _file("modify.txt", b"before"),
            _file("delete.txt", b"remove"),
        ],
    )
    current = create_workspace_snapshot(
        "fsw_project",
        [
            _file("keep.txt", b"keep"),
            _file("modify.txt", b"after"),
            _file("create.txt", b"new"),
        ],
    )

    changeset = create_workspace_changeset(base, current, sandbox_id="sb_run")

    assert [(item.path, item.operation) for item in changeset.changes] == [
        ("create.txt", "create"),
        ("delete.txt", "delete"),
        ("modify.txt", "modify"),
    ]
    assert changeset.workspace_id == "fsw_project"
    assert changeset.base_snapshot_hash == base.snapshot_hash
    assert len(changeset.changeset_hash) == 64


def test_changeset_rejects_protected_paths_and_traversal() -> None:
    base = create_workspace_snapshot("fsw_project", [])
    protected = create_workspace_snapshot(
        "fsw_project", [_file(".git/config", b"unsafe")]
    )

    with pytest.raises(WorkspaceSnapshotError, match="protected"):
        create_workspace_changeset(base, protected, sandbox_id="sb_run")
    with pytest.raises(ValidationError, match="safe relative paths"):
        WorkspaceChange(operation="create", path="../outside.txt")


def test_changeset_enforces_changed_file_and_byte_limits(monkeypatch) -> None:
    base = create_workspace_snapshot("fsw_project", [])
    two_files = create_workspace_snapshot(
        "fsw_project", [_file("a.txt", b"a"), _file("b.txt", b"b")]
    )
    monkeypatch.setattr(
        "backend.sandbox.workspace_snapshot.MAX_WORKSPACE_CHANGED_FILES", 1
    )
    with pytest.raises(WorkspaceSnapshotError, match="too many"):
        create_workspace_changeset(base, two_files, sandbox_id="sb_run")

    monkeypatch.setattr(
        "backend.sandbox.workspace_snapshot.MAX_WORKSPACE_CHANGED_FILES", 50
    )
    monkeypatch.setattr(
        "backend.sandbox.workspace_snapshot.MAX_WORKSPACE_CHANGED_FILE_BYTES", 1
    )
    with pytest.raises(WorkspaceSnapshotError, match="file exceeds"):
        create_workspace_changeset(
            base,
            create_workspace_snapshot("fsw_project", [_file("large.txt", b"xx")]),
            sandbox_id="sb_run",
        )

    monkeypatch.setattr(
        "backend.sandbox.workspace_snapshot.MAX_WORKSPACE_CHANGED_FILE_BYTES", 5
    )
    monkeypatch.setattr(
        "backend.sandbox.workspace_snapshot.MAX_WORKSPACE_TOTAL_CHANGED_BYTES", 3
    )
    with pytest.raises(WorkspaceSnapshotError, match="total size"):
        create_workspace_changeset(
            base,
            create_workspace_snapshot(
                "fsw_project", [_file("a.txt", b"aa"), _file("b.txt", b"bb")]
            ),
            sandbox_id="sb_run",
        )


def test_sandbox_manager_captures_changes_before_cleanup(tmp_path) -> None:
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    (selected / "src" / "modify.txt").write_text("before", encoding="utf-8")
    (selected / "src" / "delete.txt").write_text("remove", encoding="utf-8")
    inputs = tuple(
        SandboxInputFile(
            file_id=f"source-{index}",
            display_name=name,
            source_path=selected / "src" / name,
            relative_path=f"src/{name}",
            expected_mode=0o644,
        )
        for index, name in enumerate(("modify.txt", "delete.txt"), start=1)
    )

    class EditingRuntime:
        def execute_python(self, request, *, workspace):
            (workspace.workspace_dir / "src" / "modify.txt").write_text(
                "after", encoding="utf-8"
            )
            (workspace.workspace_dir / "src" / "delete.txt").unlink()
            (workspace.workspace_dir / "src" / "create.txt").write_text(
                "new", encoding="utf-8"
            )
            return SandboxExecutionResult(
                sandbox_id=request.sandbox_id,
                status="succeeded",
                duration_ms=1,
            )

    manager = SandboxManager(
        EditingRuntime(),
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )
    result = manager.execute_python(
        "pass",
        input_files=inputs,
        workspace_write=True,
        workspace_id="fsw_project",
    )

    assert result.workspace_changeset is not None
    assert [
        (item.path, item.operation) for item in result.workspace_changeset.changes
    ] == [
        ("src/create.txt", "create"),
        ("src/delete.txt", "delete"),
        ("src/modify.txt", "modify"),
    ]
    retained = (
        tmp_path
        / "artifacts"
        / "workspace_changes"
        / result.sandbox_id
        / "src"
        / "modify.txt"
    )
    assert retained.read_text(encoding="utf-8") == "after"
    assert (selected / "src" / "modify.txt").read_text(encoding="utf-8") == "before"
