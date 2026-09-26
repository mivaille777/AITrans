from __future__ import annotations

import pytest

from backend.sandbox.errors import SandboxExecutionError, SandboxInvalidInputError
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionRequest, SandboxExecutionResult


class FakeRuntime:
    def __init__(self, result: SandboxExecutionResult | None = None) -> None:
        self.result = result
        self.requests: list[SandboxExecutionRequest] = []
        self.error: Exception | None = None

    def health(self):
        raise NotImplementedError

    def execute_python(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
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


@pytest.mark.parametrize("code", ["", " ", "\n\t"])
def test_empty_code_is_rejected(code: str) -> None:
    with pytest.raises(SandboxInvalidInputError) as error:
        SandboxManager(FakeRuntime()).execute_python(code)

    assert error.value.code == "sandbox_invalid_input"


def test_code_over_limit_is_rejected_before_runtime() -> None:
    runtime = FakeRuntime()

    with pytest.raises(SandboxInvalidInputError):
        SandboxManager(runtime).execute_python("x" * 50_001)

    assert runtime.requests == []


def test_success_returns_typed_result_and_unique_sandbox_id() -> None:
    runtime = FakeRuntime(_success())
    manager = SandboxManager(runtime)

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


def test_runtime_sandbox_errors_keep_stable_error_code() -> None:
    runtime = FakeRuntime(_success())
    runtime.error = SandboxExecutionError("execution failed")

    with pytest.raises(SandboxExecutionError) as error:
        SandboxManager(runtime).execute_python("print(1)")

    assert error.value.code == "sandbox_execution_failed"


def test_unexpected_runtime_exception_is_normalized() -> None:
    runtime = FakeRuntime(_success())
    runtime.error = RuntimeError("internal detail")

    with pytest.raises(SandboxExecutionError) as error:
        SandboxManager(runtime).execute_python("print(1)")

    assert error.value.code == "sandbox_execution_failed"
    assert str(error.value) == "Python sandbox execution failed."
