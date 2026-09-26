"""Typed Agent capability for executing Python in the isolated sandbox."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    TypedAgentToolDefinition,
    typed_tool_definition,
)
from backend.sandbox.models import SandboxExecutionResult


class PythonExecuteArgs(AgentToolModel):
    # Python whitespace is meaningful. Override the shared AgentToolModel's
    # string stripping so execution sees the program the planner supplied.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    code: str = Field(min_length=1, max_length=50_000)


class PythonOutputFile(AgentToolModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    file_id: str
    relative_path: str
    size_bytes: int
    sha256: str


class PythonExecuteResultData(AgentToolModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    sandbox_id: str
    runtime: str
    image: str
    status: str
    exit_code: int | None = None
    duration_ms: int
    timed_out: bool
    output_limit_exceeded: bool
    oom_killed: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout: str
    stderr: str
    output_files: list[PythonOutputFile] = Field(default_factory=list)


def _output_text(result: SandboxExecutionResult) -> str:
    parts = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    if parts:
        return "\n".join(parts)
    if result.timed_out:
        return "Python execution timed out."
    if result.output_limit_exceeded:
        return "Python execution exceeded the output limit."
    if result.oom_killed:
        return "Python execution exceeded the memory limit."
    if result.exit_code not in (None, 0):
        return f"Python execution exited with code {result.exit_code}."
    return "Python execution completed without output."


def build_python_sandbox_tool_definition(
    sandbox_manager: Any,
) -> TypedAgentToolDefinition:
    """Build the Python capability around the provider-neutral manager API."""

    def execute(
        _context: AgentToolInvocationContext,
        args: PythonExecuteArgs,
    ) -> AgentToolExecutionResult:
        result = sandbox_manager.execute_python(args.code)
        if not isinstance(result, SandboxExecutionResult):
            # Keep the public tool contract stable even for a faulty adapter.
            result = SandboxExecutionResult.model_validate(result)
        data = PythonExecuteResultData(
            sandbox_id=result.sandbox_id,
            runtime=result.runtime,
            image=result.image,
            status=result.status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            output_limit_exceeded=result.output_limit_exceeded,
            oom_killed=result.oom_killed,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            stdout=result.stdout,
            stderr=result.stderr,
            output_files=[
                PythonOutputFile.model_validate(item.model_dump())
                for item in result.output_files
            ],
        )
        return AgentToolExecutionResult(
            tool_name="python_execute",
            output_text=_output_text(result),
            effect="compute",
            provider="sandbox",
            model=result.runtime,
            data=data.model_dump(mode="json"),
        )

    return typed_tool_definition(
        name="python_execute",
        title="Python Sandbox",
        description=(
            "Execute Python code in an isolated, network-disabled sandbox "
            "for calculations, data processing, and local code tasks."
        ),
        category="compute",
        effect="compute",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=PythonExecuteArgs,
        result_model=PythonExecuteResultData,
        executor=execute,
        retry_policy="never",
        timeout_seconds=40.0,
        parallel_safe=False,
        idempotent=False,
    )


__all__ = [
    "PythonExecuteArgs",
    "PythonExecuteResultData",
    "PythonOutputFile",
    "build_python_sandbox_tool_definition",
]
