"""Typed Agent capability for running allowlisted argv commands in Docker."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, model_validator

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    TypedAgentToolDefinition,
    typed_tool_definition,
)
from backend.models.sandbox_permissions import ExecutionPolicy, PermissionDecision
from backend.sandbox.command_models import SandboxCommandRequest, SandboxCommandResult
from backend.sandbox.command_runtime import SandboxCommandExecutor
from backend.sandbox.manager import SandboxManager


class CommandExecuteArgs(AgentToolModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = Field(default=".", min_length=1, max_length=1024)
    timeout_seconds: float = Field(default=30, gt=0, le=30)

    @model_validator(mode="after")
    def validate_sandbox_command(self) -> CommandExecuteArgs:
        SandboxCommandRequest.model_validate(self.model_dump())
        return self


class CommandExecuteResultData(AgentToolModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    sandbox_id: str
    argv: list[str]
    status: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int
    timed_out: bool = False
    oom_killed: bool = False
    output_limit_exceeded: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    runtime: str = "docker"
    image: str = ""
    permission_decision: PermissionDecision | None = None


def _result_text(result: SandboxCommandResult) -> str:
    if result.status == "denied":
        reason = (
            result.permission_decision.reason
            if result.permission_decision
            else result.stderr
        )
        return f"Command denied: {reason}"
    if result.status == "approval_required":
        reason = (
            result.permission_decision.reason
            if result.permission_decision
            else result.stderr
        )
        return f"Command needs approval: {reason}"
    if result.timed_out:
        return "Command execution timed out."
    if result.output_limit_exceeded:
        return "Command execution exceeded the output limit."
    if result.oom_killed:
        return "Command execution exceeded the memory limit."
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if output:
        return output
    if result.exit_code not in (None, 0):
        return f"Command exited with code {result.exit_code}."
    return "Command completed without output."


def build_command_execute_tool_definition(
    sandbox_manager: SandboxManager,
    *,
    filesystem_workspace_service: Any | None = None,
) -> TypedAgentToolDefinition:
    executor = SandboxCommandExecutor(sandbox_manager)

    def execute(
        context: AgentToolInvocationContext,
        args: CommandExecuteArgs,
    ) -> AgentToolExecutionResult:
        workspace_id = context.filesystem_workspace_id.strip()
        input_files = ()
        if workspace_id:
            if filesystem_workspace_service is None:
                raise ValueError("Filesystem workspace support is unavailable.")
            snapshot = filesystem_workspace_service.snapshot(workspace_id)
            input_files = snapshot.input_files

        result = executor.execute(
            SandboxCommandRequest.model_validate(args.model_dump()),
            execution_policy=ExecutionPolicy(
                profile="workspace_write",
                workspace_id=workspace_id,
            ),
            input_files=input_files,
            run_id=context.run_id,
            tool_call_id=context.tool_call_id,
        )
        data = CommandExecuteResultData.model_validate(result.model_dump())
        return AgentToolExecutionResult(
            tool_name="command_execute",
            output_text=_result_text(result),
            effect="compute",
            provider="sandbox",
            model=result.runtime,
            data=data.model_dump(mode="json"),
        )

    return typed_tool_definition(
        name="command_execute",
        title="Sandbox Command",
        description=(
            "Run one allowlisted command as an argv array inside an isolated Docker "
            "sandbox. Commands do not use a shell, have bounded runtime and output, "
            "and may read only files from an explicitly selected workspace copy."
        ),
        category="compute",
        effect="compute",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=CommandExecuteArgs,
        result_model=CommandExecuteResultData,
        executor=execute,
        retry_policy="never",
        timeout_seconds=40.0,
        parallel_safe=False,
        idempotent=False,
    )


__all__ = [
    "CommandExecuteArgs",
    "CommandExecuteResultData",
    "build_command_execute_tool_definition",
]
