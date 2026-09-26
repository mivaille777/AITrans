from __future__ import annotations

from backend.agent_tools.command import CommandExecuteArgs
from backend.sandbox.models import SandboxExecutionResult
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.sandbox_approval_service import SandboxApprovalService
from backend.services.sandbox_network_permission_service import (
    SandboxNetworkPermissionService,
)


class FakeSandboxManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_python(self, code: str, **kwargs) -> SandboxExecutionResult:
        self.calls.append((code, dict(kwargs)))
        return SandboxExecutionResult(
            sandbox_id=str(kwargs.get("sandbox_id", "sb_command")),
            status="succeeded",
            exit_code=0,
            stdout="Python 3.12.0\n",
            duration_ms=7,
            stdout_bytes=13,
            image="aitrans-python-sandbox:v1",
        )


def test_command_execute_is_typed_and_uses_argv_array() -> None:
    manager = FakeSandboxManager()
    registry = AgentToolRegistry(sandbox_manager=manager)
    tool = registry.get_tool("command_execute")

    assert tool is not None
    assert tool.effect == "compute"
    assert tool.input_schema["argv"]["type"] == "array"
    assert tool.input_schema["argv"]["maxItems"] == 64
    assert "hostname" in tool.input_schema["network_host"]["description"]
    assert "same Agent run" in tool.input_schema["network_approval_id"]["description"]
    assert tool.requires_confirmation is False

    arguments = registry.validate_planner_arguments(
        "command_execute", {"argv": ["python", "--version"], "cwd": "."}
    )
    result = registry.execute("command_execute", **arguments)

    assert manager.calls
    assert "shell=False" in manager.calls[0][0]
    assert result.output_text == "Python 3.12.0\n"
    assert result.data["argv"] == ["python", "--version"]
    assert result.data["status"] == "succeeded"


def test_command_execute_denies_unknown_executable_without_runtime_call() -> None:
    manager = FakeSandboxManager()
    registry = AgentToolRegistry(sandbox_manager=manager)

    result = registry.execute("command_execute", argv=["curl", "https://example.com"])

    assert manager.calls == []
    assert result.data["status"] == "denied"
    decision = result.data["permission_decision"]
    assert decision["decision"] == "deny"


def test_command_execute_rejects_non_array_argv() -> None:
    registry = AgentToolRegistry(sandbox_manager=FakeSandboxManager())

    try:
        registry.validate_planner_arguments(
            "command_execute", {"argv": "python --version"}
        )
    except ValueError as exc:
        assert "must be an array" in str(exc)
    else:
        raise AssertionError("string commands must not be parsed as shell input")


def test_command_execute_args_reject_shell_and_path_authority_fields() -> None:
    try:
        CommandExecuteArgs.model_validate(
            {"argv": ["python", "--version"], "shell": True}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("shell execution must not be user configurable")


def test_command_execute_trace_does_not_persist_raw_arguments() -> None:
    registry = AgentToolRegistry(sandbox_manager=FakeSandboxManager())
    raw = ["python", "-c", "print('secret-value')"]

    trace_arguments = registry.trace_arguments("command_execute", {"argv": raw})

    assert trace_arguments["argv_count"] == len(raw)
    assert "secret-value" not in str(trace_arguments)


def test_command_tool_requires_and_consumes_single_host_approval() -> None:
    manager = FakeSandboxManager()
    approvals = SandboxApprovalService()
    registry = AgentToolRegistry(
        sandbox_manager=manager,
        sandbox_network_permission_service=SandboxNetworkPermissionService(approvals),
    )

    pending = registry.execute(
        "command_execute",
        argv=["python", "--version"],
        network_host="pypi.org",
        run_id="run-network",
        tool_call_id="call-network-1",
    )

    approval_id = pending.data["approval_id"]
    assert pending.data["status"] == "approval_required"
    assert pending.output_text.startswith(f"Command needs approval ({approval_id})")
    assert manager.calls == []
    approvals.approve(approval_id)

    completed = registry.execute(
        "command_execute",
        argv=["python", "--version"],
        network_host="pypi.org",
        network_approval_id=approval_id,
        run_id="run-network",
        tool_call_id="call-network-2",
    )

    assert completed.data["status"] == "succeeded"
    assert manager.calls[0][1]["network_policy"].mode == "restricted"
    assert manager.calls[0][1]["network_policy"].allowed_hosts == ("pypi.org",)
