from __future__ import annotations

import stat

import pytest

from backend.sandbox.workspace import SandboxInputFile, SandboxWorkspaceManager
from backend.sandbox.workspace_snapshot import (
    WorkspaceSnapshotError,
    snapshot_directory,
)


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
