"""Provider-independent validation and lifecycle entry point."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from threading import Event
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
    MAX_SANDBOX_INPUT_FILES,
    MAX_SANDBOX_TOTAL_INPUT_BYTES,
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

    def close(self) -> None:
        close = getattr(self._runtime, "close", None)
        if callable(close):
            close()

    def health(self):
        health = getattr(self._runtime, "health", None)
        if not callable(health):
            raise TypeError("Sandbox runtime does not provide health information.")
        return health()

    @property
    def image(self) -> str:
        return str(getattr(self._runtime, "image", "") or "")

    @property
    def policy(self):
        return getattr(self._runtime, "policy", None)

    def cancel(self, sandbox_id: str) -> bool:
        cancel = getattr(self._runtime, "cancel", None)
        if not callable(cancel):
            return False
        return bool(cancel(sandbox_id))

    def execute_python(
        self,
        code: str,
        *,
        input_files: tuple[SandboxInputFile, ...] = (),
        workspace_write: bool = False,
        sandbox_id: str | None = None,
        on_stage: Callable[[str, str, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> SandboxExecutionResult:
        if not isinstance(code, str) or not code.strip():
            raise SandboxInvalidInputError("Python code must not be empty.")
        if len(code) > 50_000:
            raise SandboxInvalidInputError(
                "Python code exceeds the 50000 character limit."
            )

        request = SandboxExecutionRequest(
            sandbox_id=sandbox_id or f"sb_{uuid4().hex}",
            code=code,
        )
        workspace = self._workspace_manager.create(request.sandbox_id)
        try:
            if len(input_files) > MAX_SANDBOX_INPUT_FILES:
                raise SandboxInvalidInputError(
                    "Sandbox workspace contains too many input files."
                )
            self._emit_stage(on_stage, "staging", "running", "Copying bounded inputs.")
            staged_bytes = 0
            for input_file in input_files:
                staged_path = self._workspace_manager.stage_input(
                    workspace,
                    input_file,
                    max_bytes=MAX_SANDBOX_TOTAL_INPUT_BYTES - staged_bytes,
                )
                staged_bytes += staged_path.stat().st_size
            if workspace_write:
                self._workspace_manager.copy_inputs_to_workspace(
                    workspace, input_files
                )
            self._emit_stage(
                on_stage,
                "staging",
                "complete",
                "Inputs staged read-only with an isolated editable copy.",
            )
            if cancel_event is not None and cancel_event.is_set():
                result = SandboxExecutionResult(
                    sandbox_id=request.sandbox_id,
                    status="cancelled",
                    duration_ms=0,
                    runtime="docker",
                    image=str(getattr(self._runtime, "image", "") or ""),
                )
            else:
                result = self._execute_runtime(
                    request,
                    workspace,
                    on_stage=on_stage,
                    cancel_event=cancel_event,
                )
            if not isinstance(result, SandboxExecutionResult):
                raise SandboxExecutionError(
                    "Sandbox runtime returned an invalid result."
                )
            if result.sandbox_id != request.sandbox_id:
                raise SandboxExecutionError(
                    "Sandbox runtime returned a mismatched execution result."
                )
            if cancel_event is not None and cancel_event.is_set() and result.status != "cancelled":
                result = result.model_copy(update={"status": "cancelled"})
            if result.status == "cancelled":
                self._emit_stage(on_stage, "collect", "skipped", "Run cancelled before output collection.")
                return result
            self._emit_stage(on_stage, "collect", "running", "Collecting bounded outputs.")
            output_files = self._workspace_manager.collect_outputs(workspace)
            self._emit_stage(on_stage, "collect", "complete", "Outputs collected safely.")
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
            self._emit_stage(on_stage, "cleanup", "running", "Removing temporary host workspace.")
            try:
                self._workspace_manager.cleanup(workspace)
            except Exception:
                self._emit_stage(on_stage, "cleanup", "failed", "Temporary workspace cleanup failed.")
                raise
            else:
                self._emit_stage(on_stage, "cleanup", "complete", "Temporary workspace removed.")

    def _execute_runtime(
        self,
        request: SandboxExecutionRequest,
        workspace,
        *,
        on_stage: Callable[[str, str, str], None] | None,
        cancel_event: Event | None,
    ) -> SandboxExecutionResult:
        execute = self._runtime.execute_python
        kwargs = {"workspace": workspace}
        try:
            parameters = inspect.signature(execute).parameters
        except (TypeError, ValueError):
            parameters = {}
        supports_kwargs = any(
            item.kind is inspect.Parameter.VAR_KEYWORD
            for item in parameters.values()
        )
        if "on_stage" in parameters or supports_kwargs:
            kwargs["on_stage"] = on_stage
        if "cancel_event" in parameters or supports_kwargs:
            kwargs["cancel_event"] = cancel_event
        if on_stage is not None and "on_stage" not in kwargs:
            self._emit_stage(on_stage, "create", "running", "Starting sandbox runtime.")
        try:
            result = execute(request, **kwargs)
        except Exception:
            if on_stage is not None and "on_stage" not in kwargs:
                self._emit_stage(on_stage, "create", "failed", "Sandbox runtime failed.")
            raise
        if on_stage is not None and "on_stage" not in kwargs:
            for key in ("create", "start", "execute"):
                self._emit_stage(on_stage, key, "complete", "Runtime completed this stage.")
        return result

    @staticmethod
    def _emit_stage(
        callback: Callable[[str, str, str], None] | None,
        key: str,
        status: str,
        note: str,
    ) -> None:
        if callback is not None:
            callback(key, status, note)
