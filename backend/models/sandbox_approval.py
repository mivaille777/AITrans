"""API and service contracts for single-use sandbox approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SandboxApprovalStatus = Literal[
    "pending",
    "approved",
    "denied",
    "expired",
    "consumed",
]


class SandboxApprovalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SandboxApprovalRequest(SandboxApprovalModel):
    approval_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=128)
    permission_action: str = Field(min_length=1, max_length=64)
    target: str = Field(default="", max_length=1024)
    reason: str = Field(min_length=1, max_length=1024)
    requested_scope: dict[str, str | bool | int | None] = Field(default_factory=dict)
    status: SandboxApprovalStatus
    created_at: datetime
    expires_at: datetime


class PermissionGrant(SandboxApprovalModel):
    grant_id: str = Field(min_length=1, max_length=128)
    approval_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=64)
    scope: dict[str, str | bool | int | None]
    run_id: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=128)
    expires_at: datetime
    single_use: Literal[True] = True


__all__ = ["PermissionGrant", "SandboxApprovalRequest", "SandboxApprovalStatus"]
