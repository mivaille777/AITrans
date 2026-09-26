"""Runtime abstraction kept independent of any container provider."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Protocol

from backend.sandbox.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxRuntimeHealth,
)
from backend.sandbox.workspace import SandboxWorkspace


class SandboxRuntime(Protocol):
    def health(self) -> SandboxRuntimeHealth:
        """Return whether this runtime can execute with its configured image."""

    def execute_python(
        self,
        request: SandboxExecutionRequest,
        *,
        workspace: SandboxWorkspace,
        on_stage: Callable[[str, str, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> SandboxExecutionResult:
        """Run one request in a disposable execution environment."""

    def cancel(self, sandbox_id: str) -> bool:
        """Stop a currently running request when the provider supports it."""
