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
from backend.sandbox.workspace import (
    SandboxInputFile,
    SandboxWorkspaceManager,
)


class SandboxManager:
    """Validate untrusted code and delegate execution to a sandbox runtime."""

    def __init__(
        self,
        runtime: SandboxRuntime,
        workspace_manager: SandboxWorkspaceManager | None = None,
    ) -> None:
        self._runtime = runtime
        self._workspace_manager = workspace_manager or SandboxWorkspaceManager()

    def execute_python(
        self,
        code: str,
        *,
        input_files: tuple[SandboxInputFile, ...] = (),
    ) -> SandboxExecutionResult:
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
        workspace = self._workspace_manager.create(request.sandbox_id)
        try:
            for input_file in input_files:
                self._workspace_manager.stage_input(workspace, input_file)
            self._workspace_manager.write_code(workspace, code)
            result = self._runtime.execute_python(request, workspace=workspace)
            if not isinstance(result, SandboxExecutionResult):
                raise SandboxExecutionError(
                    "Sandbox runtime returned an invalid result."
                )
            if result.sandbox_id != request.sandbox_id:
                raise SandboxExecutionError(
                    "Sandbox runtime returned a mismatched execution result."
                )
            output_files = self._workspace_manager.collect_outputs(workspace)
            return result.model_copy(update={"output_files": output_files})
        except SandboxError:
            raise
        except ValidationError as exc:
            raise SandboxInvalidInputError("Sandbox request is invalid.") from exc
        except Exception as exc:
            raise SandboxExecutionError(
                "Python sandbox execution failed."
            ) from exc
        finally:
            self._workspace_manager.cleanup(workspace)
