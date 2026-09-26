"""Validated requests and bounded results for sandbox command execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.sandbox_permissions import PermissionDecision
from backend.sandbox.workspace_snapshot import WorkspaceChangeSet

SandboxCommandStatus = Literal[
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "oom_killed",
    "output_limit_exceeded",
    "denied",
    "approval_required",
]


class SandboxCommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class SandboxCommandRequest(SandboxCommandModel):
    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = Field(default=".", min_length=1, max_length=1024)
    timeout_seconds: float = Field(default=30, gt=0, le=30)
    network_host: str | None = Field(
        default=None,
        max_length=253,
        description="One exact hostname to request for this command; requires user approval.",
    )
    network_approval_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Approved request ID to consume for this host in the same Agent run.",
    )

    @model_validator(mode="after")
    def validate_network_approval(self) -> SandboxCommandRequest:
        if self.network_approval_id is not None and self.network_host is None:
            raise ValueError("network_approval_id requires an explicit network_host.")
        return self

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if not value or not value[0].strip():
            raise ValueError("argv must start with an executable name.")
        if any("\x00" in item for item in value):
            raise ValueError("argv must not contain null bytes.")
        if sum(len(item) for item in value) > 20_000:
            raise ValueError("argv exceeds the command argument size limit.")
        return value

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        if value == ".":
            return value
        if (
            not value
            or value.startswith(("/", "\\"))
            or "\\" in value
            or ":" in value
            or "\x00" in value
        ):
            raise ValueError("cwd must be a workspace-relative path.")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("cwd must remain within the sandbox workspace.")
        return value


class SandboxCommandResult(SandboxCommandModel):
    sandbox_id: str = Field(min_length=1, max_length=80)
    argv: list[str] = Field(min_length=1, max_length=64)
    status: SandboxCommandStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    timed_out: bool = False
    oom_killed: bool = False
    output_limit_exceeded: bool = False
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    runtime: str = "docker"
    image: str = ""
    permission_decision: PermissionDecision | None = None
    approval_id: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_changeset: WorkspaceChangeSet | None = None


__all__ = ["SandboxCommandRequest", "SandboxCommandResult", "SandboxCommandStatus"]
