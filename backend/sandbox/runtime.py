"""Runtime abstraction kept independent of any container provider."""

from __future__ import annotations

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
    ) -> SandboxExecutionResult:
        """Run one request in a disposable execution environment."""
