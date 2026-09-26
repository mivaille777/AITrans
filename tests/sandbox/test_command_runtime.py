from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.models.sandbox_permissions import ExecutionPolicy
from backend.sandbox.command_models import SandboxCommandRequest
from backend.sandbox.command_runtime import SandboxCommandExecutor
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.workspace import SandboxInputFile


class FakeSandboxManager:
    image = "aitrans-python-sandbox:v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.result = SandboxExecutionResult(
            sandbox_id="sb_test",
            status="succeeded",
            exit_code=0,
            stdout="Python 3.12.0\n",
            duration_ms=25,
            stdout_bytes=13,
            image=self.image,
        )

    def execute_python(self, code: str, **kwargs) -> SandboxExecutionResult:
        self.calls.append((code, dict(kwargs)))
        return self.result.model_copy(
            update={"sandbox_id": str(kwargs.get("sandbox_id", self.result.sandbox_id))}
        )


def _executor() -> tuple[SandboxCommandExecutor, FakeSandboxManager]:
    manager = FakeSandboxManager()
    return SandboxCommandExecutor(manager), manager


def _policy(*, workspace_id: str = "") -> ExecutionPolicy:
    return ExecutionPolicy(profile="workspace_write", workspace_id=workspace_id)


def test_allowed_argv_runs_through_shell_free_sandbox_runner() -> None:
    executor, manager = _executor()

    result = executor.execute(
        SandboxCommandRequest(argv=["python", "--version"]),
        execution_policy=_policy(),
    )

    assert result.status == "succeeded"
    assert result.argv == ["python", "--version"]
    assert result.stdout == "Python 3.12.0\n"
    assert len(manager.calls) == 1
    runner_code = manager.calls[0][0]
    compile(runner_code, "<sandbox-command-runner>", "exec")
    assert "subprocess.run(" in runner_code
    assert "shell=False" in runner_code
    assert "shell=True" not in runner_code
    assert manager.calls[0][1]["sandbox_id"] == result.sandbox_id


def test_selected_workspace_gets_an_editable_sandbox_copy() -> None:
    executor, manager = _executor()

    result = executor.execute(
        SandboxCommandRequest(argv=["python", "--version"]),
        execution_policy=_policy(workspace_id="fsw_selected"),
        input_files=(SandboxInputFile("file-1", "a.txt", Path("a.txt")),),
    )

    assert result.status == "succeeded"
    assert manager.calls[0][1]["workspace_write"] is True


@pytest.mark.parametrize("executable", ["/bin/sh", "docker", "curl", "powershell.exe"])
def test_non_allowlisted_executable_is_denied_before_runtime(executable: str) -> None:
    executor, manager = _executor()

    result = executor.execute(
        SandboxCommandRequest(argv=[executable, "-c", "echo unsafe"]),
        execution_policy=_policy(),
    )

    assert result.status == "denied"
    assert result.permission_decision is not None
    assert result.permission_decision.decision == "deny"
    assert manager.calls == []


def test_cwd_escape_is_rejected_before_runtime() -> None:
    executor, manager = _executor()

    with pytest.raises(ValidationError):
        request = SandboxCommandRequest(argv=["python", "--version"], cwd="../../")
        executor.execute(request, execution_policy=_policy())

    assert manager.calls == []


def test_reading_files_requires_selected_workspace_policy() -> None:
    executor, manager = _executor()

    result = executor.execute(
        SandboxCommandRequest(argv=["python", "--version"]),
        execution_policy=_policy(),
        input_files=(SandboxInputFile("file-1", "a.txt", Path("a.txt")),),
    )

    assert result.status == "denied"
    assert result.permission_decision is not None
    assert result.permission_decision.reason_code == "policy.workspace_required"
    assert manager.calls == []


def test_command_timeout_marker_is_reported_as_timed_out() -> None:
    executor, manager = _executor()
    manager.result = manager.result.model_copy(
        update={
            "status": "failed",
            "exit_code": 124,
            "stderr": "[AITRANS_COMMAND_TIMEOUT]",
        }
    )

    result = executor.execute(
        SandboxCommandRequest(argv=["python", "-c", "while True: pass"]),
        execution_policy=_policy(),
    )

    assert result.timed_out is True
    assert result.status == "timed_out"
    assert result.exit_code == 124
    assert result.stderr == ""


def test_output_limit_state_is_preserved() -> None:
    executor, manager = _executor()
    manager.result = manager.result.model_copy(
        update={
            "status": "output_limit_exceeded",
            "output_limit_exceeded": True,
            "stdout_bytes": 1024 * 1024,
        }
    )

    result = executor.execute(
        SandboxCommandRequest(argv=["python", "--version"]),
        execution_policy=_policy(),
    )

    assert result.status == "output_limit_exceeded"
    assert result.output_limit_exceeded is True
