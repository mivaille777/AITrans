from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.models.sandbox_permissions import ExecutionPolicy
from backend.sandbox.command_models import SandboxCommandRequest
from backend.sandbox.command_runtime import SandboxCommandExecutor
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.workspace import SandboxInputFile
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_network_permission_service import (
    SandboxNetworkPermissionService,
)


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


def _executor(
    *,
    network_permission_service: SandboxNetworkPermissionService | None = None,
) -> tuple[SandboxCommandExecutor, FakeSandboxManager]:
    manager = FakeSandboxManager()
    return (
        SandboxCommandExecutor(
            manager,
            network_permission_service=network_permission_service,
        ),
        manager,
    )


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
    assert manager.calls[0][1]["network_policy"].mode == "none"
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


def test_network_is_pending_until_approval_then_uses_exact_host_policy() -> None:
    approvals = SandboxApprovalService()
    network_permissions = SandboxNetworkPermissionService(approvals)
    executor, manager = _executor(network_permission_service=network_permissions)
    request = SandboxCommandRequest(
        argv=["python", "-c", "print('network')"],
        network_host="pypi.org",
    )

    pending = executor.execute(
        request,
        execution_policy=_policy(),
        run_id="run-1",
        tool_call_id="call-1",
    )

    assert pending.status == "approval_required"
    assert pending.approval_id
    assert pending.permission_decision is not None
    assert pending.permission_decision.decision == "approval_required"
    assert manager.calls == []

    approvals.approve(pending.approval_id)
    result = executor.execute(
        request.model_copy(update={"network_approval_id": pending.approval_id}),
        execution_policy=_policy(),
        run_id="run-1",
        tool_call_id="call-2",
    )

    assert result.status == "succeeded"
    assert manager.calls[0][1]["network_policy"].mode == "restricted"
    assert manager.calls[0][1]["network_policy"].allowed_hosts == ("pypi.org",)
    assert approvals.get(pending.approval_id).status == "consumed"


def test_network_grant_for_wrong_run_or_host_never_reaches_runtime() -> None:
    approvals = SandboxApprovalService()
    network_permissions = SandboxNetworkPermissionService(approvals)
    executor, manager = _executor(network_permission_service=network_permissions)
    pending = executor.execute(
        SandboxCommandRequest(argv=["python", "--version"], network_host="pypi.org"),
        execution_policy=_policy(),
        run_id="run-1",
        tool_call_id="call-1",
    )
    approvals.approve(pending.approval_id)

    wrong_run = executor.execute(
        SandboxCommandRequest(
            argv=["python", "--version"],
            network_host="pypi.org",
            network_approval_id=pending.approval_id,
        ),
        execution_policy=_policy(),
        run_id="run-2",
        tool_call_id="call-2",
    )
    wrong_host = executor.execute(
        SandboxCommandRequest(
            argv=["python", "--version"],
            network_host="github.com",
            network_approval_id=pending.approval_id,
        ),
        execution_policy=_policy(),
        run_id="run-1",
        tool_call_id="call-2",
    )

    assert wrong_run.status == "denied"
    assert wrong_host.status == "denied"
    assert manager.calls == []
    assert approvals.get(pending.approval_id).status == "approved"


def test_network_approval_identifier_requires_a_host() -> None:
    with pytest.raises(ValidationError):
        SandboxCommandRequest(
            argv=["python", "--version"],
            network_approval_id="apr_test",
        )
