"""Provider-independent validation and lifecycle entry point."""

from __future__ import annotations

from uuid import uuid4

from pydantic import ValidationError

from backend.sandbox.errors import (
    SandboxError,
    SandboxExecutionError,
    SandboxInvalidInputError,
)
from backend.sandbox.models import SandboxExecutionRequest, SandboxExecutionResult
from backend.sandbox.runtime import SandboxRuntime


class SandboxManager:
    """Validate untrusted code and delegate execution to a sandbox runtime."""

    def __init__(self, runtime: SandboxRuntime) -> None:
        self._runtime = runtime

    def execute_python(self, code: str) -> SandboxExecutionResult:
        if not isinstance(code, str) or not code.strip():
            raise SandboxInvalidInputError("Python code must not be empty.")
        if len(code) > 50_000:
            raise SandboxInvalidInputError(
                "Python code exceeds the 50000 character limit."
            )

        request = SandboxExecutionRequest(
            sandbox_id=f"sb_{uuid4().hex}",
            code=code,
        )
        try:
            return self._runtime.execute_python(request)
        except SandboxError:
            raise
        except ValidationError as exc:
            raise SandboxInvalidInputError("Sandbox request is invalid.") from exc
        except Exception as exc:
            raise SandboxExecutionError(
                "Python sandbox execution failed."
            ) from exc
