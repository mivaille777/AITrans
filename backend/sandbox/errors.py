"""Stable public error contract for sandbox operations."""

from __future__ import annotations


class SandboxError(RuntimeError):
    """Base class for errors that may safely cross the sandbox boundary."""

    code = "sandbox_error"


class DockerUnavailableError(SandboxError):
    code = "docker_unavailable"


class DockerNotLinuxError(SandboxError):
    code = "docker_not_linux"


class SandboxImageMissingError(SandboxError):
    code = "sandbox_image_missing"


class SandboxCreateError(SandboxError):
    code = "sandbox_create_failed"


class SandboxStartError(SandboxError):
    code = "sandbox_start_failed"


class SandboxTimeoutError(SandboxError):
    code = "sandbox_timeout"


class SandboxExecutionError(SandboxError):
    code = "sandbox_execution_failed"


class SandboxCleanupError(SandboxError):
    code = "sandbox_cleanup_failed"


class SandboxInvalidInputError(SandboxError):
    code = "sandbox_invalid_input"
