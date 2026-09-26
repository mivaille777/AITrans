from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from backend.sandbox.errors import (
    SandboxExecutionError,
    SandboxInvalidInputError,
    SandboxOutputLimitError,
)
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY
from backend.sandbox.workspace import (
    SandboxInputFile,
    SandboxWorkspace,
    SandboxWorkspaceManager,
    docker_volume_bindings,
)


def _workspace_manager(tmp_path: Path) -> SandboxWorkspaceManager:
    return SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes",
        artifact_root=tmp_path / "artifacts",
    )


class OutputRuntime:
    def __init__(self, *, unsafe_symlink: Path | None = None) -> None:
        self.requests: list[SandboxExecutionRequest] = []
        self.unsafe_symlink = unsafe_symlink

    def health(self):
        raise NotImplementedError

    def execute_python(
        self,
        request: SandboxExecutionRequest,
        *,
        workspace: SandboxWorkspace,
    ) -> SandboxExecutionResult:
        self.requests.append(request)
        if self.unsafe_symlink is not None:
            (workspace.output_dir / "escape.txt").symlink_to(self.unsafe_symlink)
        else:
            nested = workspace.output_dir / "nested"
            nested.mkdir()
            (nested / "result.txt").write_text("ok", encoding="utf-8")
        return SandboxExecutionResult(
            sandbox_id=request.sandbox_id,
            status="succeeded",
            exit_code=0,
            duration_ms=1,
            image="aitrans-python-sandbox:v1",
        )


def test_inputs_are_copied_and_mounts_expose_only_workspace_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original.csv"
    source.write_text("id,value\n1,original\n", encoding="utf-8")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manager = _workspace_manager(tmp_path)
    workspace = manager.create("sb_" + "a" * 32)

    staged = manager.stage_input(
        workspace,
        SandboxInputFile(
            file_id="file-1",
            display_name="sample.csv",
            source_path=source,
        ),
    )
    volumes = docker_volume_bindings(workspace)

    assert staged.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert staged.resolve() != source.resolve()
    assert original_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert str(source.resolve()) not in volumes
    assert {binding["bind"]: binding["mode"] for binding in volumes.values()} == {
        "/input": "ro",
        "/workspace": "rw",
        "/output": "rw",
    }
    manager.cleanup(workspace)


@pytest.mark.parametrize(
    "display_name",
    [
        "../../escape.txt",
        r"..\..\escape.txt",
        r"C:\Users\private\secret.txt",
        "/etc/passwd",
        "..",
    ],
)
def test_input_traversal_is_rejected_before_runtime(
    display_name: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("safe", encoding="utf-8")
    runtime = OutputRuntime()
    manager = SandboxManager(runtime, _workspace_manager(tmp_path))

    with pytest.raises(SandboxInvalidInputError):
        manager.execute_python(
            "print('never run')",
            input_files=(
                SandboxInputFile(
                    file_id="file-1",
                    display_name=display_name,
                    source_path=source,
                ),
            ),
        )

    assert runtime.requests == []
    assert list((tmp_path / "sandboxes").iterdir()) == []


def test_symlink_inputs_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "outside.txt"
    source.write_text("outside", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("The current Windows environment does not allow symlink creation.")

    manager = _workspace_manager(tmp_path)
    workspace = manager.create("sb_" + "b" * 32)
    try:
        with pytest.raises(SandboxInvalidInputError):
            manager.stage_input(
                workspace,
                SandboxInputFile("file-1", "linked.txt", link),
            )
    finally:
        manager.cleanup(workspace)


def test_outputs_are_promoted_with_safe_metadata_and_workspace_is_removed(
    tmp_path: Path,
) -> None:
    runtime = OutputRuntime()
    workspace_manager = _workspace_manager(tmp_path)
    result = SandboxManager(runtime, workspace_manager).execute_python("print('safe')")

    assert len(result.output_files) == 1
    output = result.output_files[0]
    promoted = tmp_path / "artifacts" / result.sandbox_id / "nested" / "result.txt"
    assert output.file_id.startswith("sbo_")
    assert output.relative_path == "nested/result.txt"
    assert output.size_bytes == 2
    assert output.sha256 == hashlib.sha256(b"ok").hexdigest()
    assert promoted.read_text(encoding="utf-8") == "ok"
    assert not (tmp_path / "sandboxes" / result.sandbox_id).exists()
    assert str(tmp_path) not in result.model_dump_json()


def test_unsafe_output_symlink_is_rejected_and_workspace_is_cleaned(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("do not promote", encoding="utf-8")
    runtime = OutputRuntime(unsafe_symlink=outside)
    workspace_manager = _workspace_manager(tmp_path)

    with pytest.raises(SandboxExecutionError):
        SandboxManager(runtime, workspace_manager).execute_python("print('safe')")

    sandbox_dirs = tmp_path / "sandboxes"
    assert sandbox_dirs.is_dir()
    assert list(sandbox_dirs.iterdir()) == []
    assert outside.read_text(encoding="utf-8") == "do not promote"


def test_workspace_code_file_is_read_only_until_cleanup(tmp_path: Path) -> None:
    manager = _workspace_manager(tmp_path)
    workspace = manager.create("sb_" + "c" * 32)

    code_path = manager.write_code(workspace, "print('ready')")

    assert code_path.name == "main.py"
    assert code_path.read_text(encoding="utf-8") == "print('ready')"
    if os.name != "nt":
        assert code_path.stat().st_mode & 0o222 == 0
    manager.cleanup(workspace)
    assert not workspace.root.exists()


def test_output_file_count_and_size_limits_are_enforced(tmp_path: Path) -> None:
    policy = replace(
        DEFAULT_SANDBOX_POLICY,
        max_output_files=1,
        max_output_file_bytes=4,
        max_total_output_bytes=4,
    )
    manager = SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes",
        artifact_root=tmp_path / "artifacts",
        policy=policy,
    )
    workspace = manager.create("sb_" + "d" * 32)
    (workspace.output_dir / "one.txt").write_text("12345", encoding="utf-8")

    with pytest.raises(SandboxOutputLimitError) as error:
        manager.collect_outputs(workspace)

    assert error.value.code == "sandbox_file_limit"
    manager.cleanup(workspace)


def test_output_file_count_limit_is_enforced(tmp_path: Path) -> None:
    policy = replace(DEFAULT_SANDBOX_POLICY, max_output_files=1)
    manager = SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes",
        artifact_root=tmp_path / "artifacts",
        policy=policy,
    )
    workspace = manager.create("sb_" + "e" * 32)
    (workspace.output_dir / "one.txt").write_text("one", encoding="utf-8")
    (workspace.output_dir / "two.txt").write_text("two", encoding="utf-8")

    with pytest.raises(SandboxOutputLimitError):
        manager.collect_outputs(workspace)

    manager.cleanup(workspace)
