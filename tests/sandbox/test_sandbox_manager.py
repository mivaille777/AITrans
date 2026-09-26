from __future__ import annotations

import pytest

from backend.sandbox.docker_runtime import DockerSandboxRuntime
from backend.sandbox.errors import SandboxExecutionError, SandboxInvalidInputError
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionRequest, SandboxExecutionResult
from backend.sandbox.workspace import SandboxWorkspace, SandboxWorkspaceManager


class FakeRuntime:
    def __init__(self, result: SandboxExecutionResult | None = None) -> None:
        self.result = result
        self.requests: list[SandboxExecutionRequest] = []
        self.error: Exception | None = None

    def health(self):
        raise NotImplementedError

    def execute_python(
        self,
        request: SandboxExecutionRequest,
        *,
        workspace: SandboxWorkspace,
    ) -> SandboxExecutionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result.model_copy(update={"sandbox_id": request.sandbox_id})


def _success() -> SandboxExecutionResult:
    return SandboxExecutionResult(
        sandbox_id="placeholder",
        status="succeeded",
        exit_code=0,
        stdout="2\n",
        duration_ms=10,
        image="aitrans-python-sandbox:v1",
    )


def _manager(runtime: FakeRuntime, tmp_path) -> SandboxManager:
    return SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )


@pytest.mark.parametrize("code", ["", " ", "\n\t"])
def test_empty_code_is_rejected(code: str, tmp_path) -> None:
    with pytest.raises(SandboxInvalidInputError) as error:
        _manager(FakeRuntime(), tmp_path).execute_python(code)

    assert error.value.code == "sandbox_invalid_input"


def test_code_over_limit_is_rejected_before_runtime(tmp_path) -> None:
    runtime = FakeRuntime()

    with pytest.raises(SandboxInvalidInputError):
        _manager(runtime, tmp_path).execute_python("x" * 50_001)

    assert runtime.requests == []


def test_success_returns_typed_result_and_unique_sandbox_id(tmp_path) -> None:
    runtime = FakeRuntime(_success())
    manager = _manager(runtime, tmp_path)

    first = manager.execute_python("print(1 + 1)")
    second = manager.execute_python("print(2 + 2)")

    assert first.stdout == "2\n"
    assert first.status == "succeeded"
    assert first.sandbox_id.startswith("sb_")
    assert second.sandbox_id.startswith("sb_")
    assert first.sandbox_id != second.sandbox_id
    assert [request.code for request in runtime.requests] == [
        "print(1 + 1)",
        "print(2 + 2)",
    ]


def test_runtime_sandbox_errors_keep_stable_error_code(tmp_path) -> None:
    runtime = FakeRuntime(_success())
    runtime.error = SandboxExecutionError("execution failed")

    with pytest.raises(SandboxExecutionError) as error:
        _manager(runtime, tmp_path).execute_python("print(1)")

    assert error.value.code == "sandbox_execution_failed"


def test_unexpected_runtime_exception_is_normalized(tmp_path) -> None:
    runtime = FakeRuntime(_success())
    runtime.error = RuntimeError("internal detail")

    with pytest.raises(SandboxExecutionError) as error:
        _manager(runtime, tmp_path).execute_python("print(1)")

    assert error.value.code == "sandbox_execution_failed"
    assert str(error.value) == "Python sandbox execution failed."


def test_docker_runtime_close_releases_only_its_owned_client(monkeypatch) -> None:
    class FakeClient:
        closed = False

        def close(self) -> None:
            self.closed = True

    owned = FakeClient()
    monkeypatch.setattr(
        "backend.sandbox.docker_runtime.docker.from_env",
        lambda **_kwargs: owned,
    )
    runtime = DockerSandboxRuntime()
    assert runtime._get_client() is owned
    runtime.close()
    assert owned.closed

    provided = FakeClient()
    injected_runtime = DockerSandboxRuntime(client=provided)
    injected_runtime.close()
    assert not provided.closed
    assert injected_runtime._get_client() is provided
