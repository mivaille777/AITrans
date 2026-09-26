from __future__ import annotations

import hashlib

import pytest

from backend.agent_tools.sandbox import PythonExecuteArgs
from backend.api import dependencies
from backend.api.agent import list_agent_tools
from backend.sandbox.models import (
    SandboxExecutionResult,
    SandboxOutputFile,
    SandboxRuntimeHealth,
)
from backend.services.agent_tool_registry import AgentToolRegistry


class FakeSandboxManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_python(self, code: str) -> SandboxExecutionResult:
        self.calls.append(code)
        return SandboxExecutionResult(
            sandbox_id="sb_test",
            status="succeeded",
            exit_code=0,
            stdout="42\n",
            stderr="",
            duration_ms=12,
            stdout_bytes=3,
            stderr_bytes=0,
            output_files=[
                SandboxOutputFile(
                    file_id="file-1",
                    relative_path="result.txt",
                    size_bytes=2,
                    sha256="a" * 64,
                )
            ],
        )


def test_python_execute_is_typed_and_exposes_only_code() -> None:
    manager = FakeSandboxManager()
    registry = AgentToolRegistry(sandbox_manager=manager)

    tool = registry.get_tool("python_execute")
    assert tool is not None
    assert set(tool.input_schema) == {"code"}
    assert tool.input_schema["code"]["minLength"] == 1
    assert tool.input_schema["code"]["maxLength"] == 50_000
    assert tool.effect == "compute"
    assert tool.requires_confirmation is False
    assert tool.requires_reading_context is False
    assert tool.timeout_seconds == 40.0
    assert tool.parallel_safe is False
    assert tool.idempotent is False
    assert registry.allows_safe_retry("python_execute") is False
    catalog = list_agent_tools(registry)
    catalog_tool = next(item for item in catalog.tools if item.name == "python_execute")
    assert catalog_tool.category == "compute"
    assert set(catalog_tool.input_schema) == {"code"}

    code = "print(40 + 2)\n"
    result = registry.execute("python_execute", code=code)

    assert manager.calls == [code]
    assert result.output_text == "42\n"
    assert result.effect == "compute"
    assert result.data == {
        "sandbox_id": "sb_test",
        "runtime": "docker",
        "image": "",
        "status": "succeeded",
        "exit_code": 0,
        "duration_ms": 12,
        "timed_out": False,
        "output_limit_exceeded": False,
        "oom_killed": False,
        "stdout_bytes": 3,
        "stderr_bytes": 0,
        "stdout": "42\n",
        "stderr": "",
        "output_files": [
            {
                "file_id": "file-1",
                "relative_path": "result.txt",
                "size_bytes": 2,
                "sha256": "a" * 64,
            }
        ],
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        "image",
        "network",
        "mount",
        "host_path",
        "timeout",
        "memory",
        "cpu",
        "docker_args",
    ],
)
def test_python_execute_rejects_docker_authority_arguments(forbidden: str) -> None:
    registry = AgentToolRegistry(sandbox_manager=FakeSandboxManager())

    with pytest.raises(ValueError, match="outside its authority"):
        registry.validate_planner_arguments(
            "python_execute", {"code": "print(1)", forbidden: "untrusted"}
        )


def test_python_execute_args_preserve_python_whitespace() -> None:
    code = "\nprint('first')\nprint('second')\n"

    assert PythonExecuteArgs(code=code).code == code


def test_python_trace_arguments_hash_code_but_leave_other_tools_unchanged() -> None:
    registry = AgentToolRegistry(sandbox_manager=FakeSandboxManager())
    code = "print('private source')"

    assert registry.trace_arguments("python_execute", {"code": code}) == {
        "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "code_chars": len(code),
    }
    ordinary = {"query": "a normal argument"}
    assert registry.trace_arguments("search_research_notes", ordinary) == ordinary


def test_sandbox_manager_dependency_requires_enable_and_runtime_health(
    monkeypatch,
) -> None:
    class FakeRuntime:
        def __init__(self, *, available: bool) -> None:
            self._health = SandboxRuntimeHealth(available=available)
            self.closed = False

        def health(self) -> SandboxRuntimeHealth:
            return self._health

        def close(self) -> None:
            self.closed = True

    dependencies.close_sandbox_manager()
    monkeypatch.delenv("AITRANS_SANDBOX_ENABLED", raising=False)
    assert dependencies.get_sandbox_manager() is None
    assert "python_execute" not in {
        tool.name for tool in AgentToolRegistry(sandbox_manager=None).list_tools()
    }

    unavailable = FakeRuntime(available=False)
    monkeypatch.setenv("AITRANS_SANDBOX_ENABLED", "true")
    monkeypatch.setattr(
        dependencies,
        "DockerSandboxRuntime",
        lambda **_kwargs: unavailable,
    )
    assert dependencies.get_sandbox_manager() is None
    assert unavailable.closed

    available = FakeRuntime(available=True)
    monkeypatch.setattr(
        dependencies,
        "DockerSandboxRuntime",
        lambda **_kwargs: available,
    )
    manager = dependencies.get_sandbox_manager()
    assert manager is not None
    assert dependencies.get_sandbox_manager() is manager
    dependencies.close_sandbox_manager()
    assert available.closed
