"""Run controlled argv commands inside the existing disposable Docker sandbox."""

from __future__ import annotations

import json
from collections.abc import Callable
from threading import Event
from uuid import uuid4

from backend.models.sandbox_permissions import (
    ExecutionPolicy,
    PermissionDecision,
    PermissionRequest,
)
from backend.sandbox.command_models import SandboxCommandRequest, SandboxCommandResult
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.network_policy import DEFAULT_NETWORK_POLICY
from backend.sandbox.permissions import PermissionPolicyEngine
from backend.sandbox.workspace import SandboxInputFile
from backend.services.sandbox_network_permission_service import (
    SandboxNetworkPermissionError,
    SandboxNetworkPermissionService,
)

_COMMAND_TIMEOUT_MARKER = "[AITRANS_COMMAND_TIMEOUT]"


class SandboxCommandExecutor:
    """Validate policy and run argv through Python's shell-free subprocess API in Docker."""

    def __init__(
        self,
        sandbox_manager: SandboxManager,
        *,
        permission_policy_engine: PermissionPolicyEngine | None = None,
        network_permission_service: SandboxNetworkPermissionService | None = None,
    ) -> None:
        self._sandbox_manager = sandbox_manager
        self._policy_engine = permission_policy_engine or PermissionPolicyEngine()
        self._network_permission_service = network_permission_service

    def execute(
        self,
        request: SandboxCommandRequest,
        *,
        execution_policy: ExecutionPolicy,
        input_files: tuple[SandboxInputFile, ...] = (),
        run_id: str = "",
        tool_call_id: str = "",
        on_stage: Callable[[str, str, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> SandboxCommandResult:
        if not isinstance(request, SandboxCommandRequest):
            request = SandboxCommandRequest.model_validate(request)
        if not isinstance(execution_policy, ExecutionPolicy):
            execution_policy = ExecutionPolicy.model_validate(execution_policy)

        sandbox_id = f"sb_{uuid4().hex}"
        command_permission = self._policy_engine.evaluate(
            PermissionRequest(
                action="command.execute",
                target=request.argv[0],
                reason="Run a command inside the isolated sandbox.",
                tool_name="command_execute",
                run_id=run_id,
                tool_call_id=tool_call_id,
            ),
            execution_policy,
        )
        if command_permission.decision != "allow":
            return self._permission_result(sandbox_id, request, command_permission)

        if input_files:
            filesystem_permission = self._policy_engine.evaluate(
                PermissionRequest(
                    action="filesystem.read",
                    target="/input",
                    reason="Read explicitly selected workspace files.",
                    tool_name="command_execute",
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                ),
                execution_policy,
            )
            if filesystem_permission.decision != "allow":
                return self._permission_result(
                    sandbox_id, request, filesystem_permission
                )

        workspace_write = bool(execution_policy.workspace_id.strip())
        if workspace_write:
            write_permission = self._policy_engine.evaluate(
                PermissionRequest(
                    action="filesystem.write_sandbox",
                    target="/workspace",
                    reason="Edit an isolated copy of the selected workspace.",
                    tool_name="command_execute",
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                ),
                execution_policy,
            )
            if write_permission.decision != "allow":
                return self._permission_result(sandbox_id, request, write_permission)

        network_policy = DEFAULT_NETWORK_POLICY
        if request.network_host is not None:
            if self._network_permission_service is None:
                return self._network_error_result(
                    sandbox_id,
                    request,
                    SandboxNetworkPermissionError(
                        "network_permission_service_unavailable",
                        "Sandbox network approval is unavailable.",
                        status_code=503,
                    ),
                )
            if request.network_approval_id is None:
                try:
                    approval = self._network_permission_service.request_approval(
                        request.network_host,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                    )
                except SandboxNetworkPermissionError as exc:
                    return self._network_error_result(sandbox_id, request, exc)
                decision = PermissionDecision(
                    decision="approval_required",
                    reason_code="policy.network_approval_required",
                    reason=approval.reason,
                    granted_scope=approval.requested_scope,
                )
                return SandboxCommandResult(
                    sandbox_id=sandbox_id,
                    argv=list(request.argv),
                    status="approval_required",
                    stderr=approval.reason,
                    duration_ms=0,
                    permission_decision=decision,
                    approval_id=approval.approval_id,
                )
            try:
                network_policy = self._network_permission_service.consume_grant(
                    request.network_approval_id,
                    request.network_host,
                    run_id=run_id,
                )
            except SandboxNetworkPermissionError as exc:
                return self._network_error_result(sandbox_id, request, exc)

        result = self._sandbox_manager.execute_python(
            _runner_code(request),
            input_files=input_files,
            workspace_write=workspace_write,
            workspace_id=execution_policy.workspace_id,
            network_policy=network_policy,
            sandbox_id=sandbox_id,
            on_stage=on_stage,
            cancel_event=cancel_event,
        )
        return _command_result(request, result, command_permission)

    @staticmethod
    def _network_error_result(
        sandbox_id: str,
        request: SandboxCommandRequest,
        error: SandboxNetworkPermissionError,
    ) -> SandboxCommandResult:
        decision = PermissionDecision(
            decision="deny",
            reason_code=error.code,
            reason=str(error),
        )
        return SandboxCommandResult(
            sandbox_id=sandbox_id,
            argv=list(request.argv),
            status="denied",
            stderr=str(error),
            duration_ms=0,
            permission_decision=decision,
        )

    @staticmethod
    def _permission_result(
        sandbox_id: str,
        request: SandboxCommandRequest,
        decision,
    ) -> SandboxCommandResult:
        status = (
            "approval_required"
            if decision.decision == "approval_required"
            else "denied"
        )
        return SandboxCommandResult(
            sandbox_id=sandbox_id,
            argv=list(request.argv),
            status=status,
            stderr=decision.reason,
            duration_ms=0,
            permission_decision=decision,
        )


def _runner_code(request: SandboxCommandRequest) -> str:
    payload = json.dumps(
        {
            "argv": request.argv,
            "cwd": request.cwd,
            "timeout_seconds": request.timeout_seconds,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload_literal = json.dumps(payload, ensure_ascii=True)
    return f"""from __future__ import annotations

import json
import os
import subprocess
import sys

request = json.loads({payload_literal})
workspace = os.path.realpath("/workspace")
working_directory = workspace
try:
    for component in request["cwd"].split("/") if request["cwd"] != "." else ():
        working_directory = os.path.join(working_directory, component)
        if os.path.islink(working_directory):
            raise RuntimeError("Sandbox cwd contains a symbolic link.")
        if os.path.exists(working_directory):
            if not os.path.isdir(working_directory):
                raise RuntimeError("Sandbox cwd is not a directory.")
        else:
            os.mkdir(working_directory)
    if os.path.commonpath((workspace, os.path.realpath(working_directory))) != workspace:
        raise RuntimeError("Sandbox cwd escapes the workspace.")
except (OSError, RuntimeError, ValueError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(126)

try:
    completed = subprocess.run(
        request["argv"],
        cwd=working_directory,
        shell=False,
        check=False,
        timeout=request["timeout_seconds"],
    )
except subprocess.TimeoutExpired:
    sys.stderr.write({_COMMAND_TIMEOUT_MARKER!r})
    sys.stderr.flush()
    raise SystemExit(124)
raise SystemExit(completed.returncode)
"""


def _command_result(
    request: SandboxCommandRequest,
    result: SandboxExecutionResult,
    permission_decision,
) -> SandboxCommandResult:
    timed_out = result.timed_out or _COMMAND_TIMEOUT_MARKER in result.stderr
    stderr = result.stderr.replace(_COMMAND_TIMEOUT_MARKER, "")
    stderr_bytes = max(
        0,
        result.stderr_bytes
        - result.stderr.count(_COMMAND_TIMEOUT_MARKER)
        * len(_COMMAND_TIMEOUT_MARKER.encode("utf-8")),
    )
    status = "timed_out" if timed_out else result.status
    exit_code = 124 if timed_out else result.exit_code
    return SandboxCommandResult(
        sandbox_id=result.sandbox_id,
        argv=list(request.argv),
        status=status,
        exit_code=exit_code,
        stdout=result.stdout,
        stderr=stderr,
        duration_ms=result.duration_ms,
        timed_out=timed_out,
        oom_killed=result.oom_killed,
        output_limit_exceeded=result.output_limit_exceeded,
        stdout_bytes=result.stdout_bytes,
        stderr_bytes=stderr_bytes,
        runtime=result.runtime,
        image=result.image,
        permission_decision=permission_decision,
        workspace_changeset=result.workspace_changeset,
    )


__all__ = ["SandboxCommandExecutor"]
