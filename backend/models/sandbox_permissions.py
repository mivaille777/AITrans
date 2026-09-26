"""Validated contracts for sandbox permissions and policy decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SandboxPermissionProfileName = Literal[
    "read_only",
    "workspace_write",
    "restricted_network",
]
SandboxPermissionDecisionKind = Literal["allow", "deny", "approval_required"]
DEFAULT_SANDBOX_COMMAND_ALLOWLIST = ("python", "pytest")


class SandboxPermissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SandboxPermissionProfile(SandboxPermissionModel):
    """One system-defined profile; callers cannot add arbitrary capabilities."""

    name: SandboxPermissionProfileName
    filesystem_read: bool
    filesystem_write_sandbox: bool
    filesystem_apply_host: Literal["deny", "approval_required"]
    network: Literal["none", "allowlist"]
    command_execution: bool
    secrets: Literal["none"]


class PermissionRequest(SandboxPermissionModel):
    """A backend-created request for one operation by one tool call."""

    action: str = Field(min_length=1, max_length=64)
    target: str = Field(default="", max_length=1024)
    reason: str = Field(min_length=1, max_length=1024)
    tool_name: str = Field(default="", max_length=128)
    run_id: str = Field(default="", max_length=128)
    tool_call_id: str = Field(default="", max_length=128)


class ExecutionPolicy(SandboxPermissionModel):
    """Server-selected policy context for a single execution."""

    # Keep this a string so an unknown or stale profile can be explicitly
    # denied by the policy engine instead of failing open at a call site.
    profile: str = Field(min_length=1, max_length=64)
    workspace_id: str = Field(default="", max_length=128)
    network_allowlist: tuple[str, ...] = Field(default=(), max_length=128)
    command_allowlist: tuple[str, ...] = Field(
        default=DEFAULT_SANDBOX_COMMAND_ALLOWLIST,
        min_length=1,
        max_length=32,
    )


class PermissionDecision(SandboxPermissionModel):
    """Structured policy outcome consumed by execution and trace services."""

    decision: SandboxPermissionDecisionKind
    reason_code: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    granted_scope: dict[str, str | bool | int | None] = Field(default_factory=dict)


__all__ = [
    "DEFAULT_SANDBOX_COMMAND_ALLOWLIST",
    "ExecutionPolicy",
    "PermissionDecision",
    "PermissionRequest",
    "SandboxPermissionDecisionKind",
    "SandboxPermissionProfile",
    "SandboxPermissionProfileName",
]
