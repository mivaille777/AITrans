"""HTTP and debug-stream contracts for Sandbox runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SandboxRunStatus = Literal[
    "pending",
    "preparing",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "output_limit_exceeded",
    "oom_killed",
]
SandboxDebugStageKey = Literal[
    "request",
    "permission",
    "approval",
    "workspace",
    "staging",
    "create",
    "start",
    "execute",
    "network",
    "changes",
    "apply",
    "collect",
    "cleanup",
]
SandboxDebugStageStatus = Literal[
    "pending", "running", "complete", "failed", "skipped"
]


class SandboxDebugModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxRuntimeHealthResponse(SandboxDebugModel):
    available: bool
    runtime: str = "docker"
    image: str = ""
    daemon_ready: bool = False
    os_type: str = ""
    server_os: str = ""
    detail: str = ""
    message: str = ""
    error_code: str | None = None


class SandboxRunSummary(SandboxDebugModel):
    sandbox_id: str
    run_id: str
    tool_call_id: str = ""
    source: Literal["agent", "manual"]
    workspace_id: str = ""
    workspace_name: str = ""
    runtime: str = "docker"
    image: str = ""
    status: SandboxRunStatus
    started_at: str
    finished_at: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    exit_code: int | None = None


class SandboxDebugStage(SandboxDebugModel):
    key: SandboxDebugStageKey
    label: str
    status: SandboxDebugStageStatus = "pending"
    elapsed_ms: int = Field(default=0, ge=0)
    note: str = ""


class SandboxActivityEvent(SandboxDebugModel):
    sequence: int = Field(ge=0)
    timestamp: str
    kind: Literal["file", "network", "process", "runtime", "policy", "approval"]
    action: str = Field(min_length=1, max_length=128)
    target: str = Field(default="", max_length=1024)
    decision: Literal[
        "allowed",
        "denied",
        "observed",
        "approval_required",
        "pending",
        "approved",
        "expired",
        "consumed",
    ]
    reason: str = Field(default="", max_length=1024)
    permission_action: str = Field(default="", max_length=128)
    policy_rule: str = Field(default="", max_length=128)
    approval_id: str = Field(default="", max_length=128)
    grant_id: str = Field(default="", max_length=128)


class SandboxResourceSample(SandboxDebugModel):
    timestamp_ms: int = Field(ge=0)
    cpu_percent: float = Field(default=0, ge=0)
    memory_bytes: int = Field(default=0, ge=0)
    pids: int = Field(default=0, ge=0)
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    output_bytes: int = Field(default=0, ge=0)


class SandboxEffectivePolicy(SandboxDebugModel):
    network: str
    root_filesystem_read_only: bool
    user: str
    cap_drop: list[str]
    no_new_privileges: bool
    seccomp: str
    cpu_limit: float
    memory_limit_bytes: int
    pids_limit: int
    timeout_seconds: float
    stdout_limit_bytes: int
    stderr_limit_bytes: int
    output_limit_bytes: int
    docker_socket_mounted: bool | None


class SandboxDebugFile(SandboxDebugModel):
    file_id: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str
    source: Literal["workspace", "generated", "runtime"]


class SandboxDebugWorkspaceChange(SandboxDebugModel):
    operation: Literal["create", "modify", "delete"]
    path: str = Field(min_length=1, max_length=1024)
    before_sha256: str | None = Field(default=None, max_length=64)
    after_sha256: str | None = Field(default=None, max_length=64)
    size_before: int | None = Field(default=None, ge=0)
    size_after: int | None = Field(default=None, ge=0)
    size_delta: int


class SandboxDebugTrace(SandboxDebugModel):
    run: SandboxRunSummary
    stages: list[SandboxDebugStage] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    activities: list[SandboxActivityEvent] = Field(default_factory=list)
    resources: list[SandboxResourceSample] = Field(default_factory=list)
    policy: SandboxEffectivePolicy
    input_files: list[SandboxDebugFile] = Field(default_factory=list)
    output_files: list[SandboxDebugFile] = Field(default_factory=list)
    workspace_changes: list[SandboxDebugWorkspaceChange] = Field(default_factory=list)
    error: str = ""


class SandboxDebugRunRequest(SandboxDebugModel):
    code: str = Field(min_length=1, max_length=50_000)
    filesystem_workspace_id: str = Field(default="", max_length=128)

    @field_validator("code")
    @classmethod
    def validate_nonblank_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Python code must not be empty.")
        return value


class SandboxDebugRunAccepted(SandboxDebugModel):
    sandbox_id: str
    run_id: str
    status: SandboxRunStatus


__all__ = [
    "SandboxActivityEvent",
    "SandboxDebugFile",
    "SandboxDebugRunAccepted",
    "SandboxDebugRunRequest",
    "SandboxDebugStage",
    "SandboxDebugTrace",
    "SandboxDebugWorkspaceChange",
    "SandboxEffectivePolicy",
    "SandboxResourceSample",
    "SandboxRunStatus",
    "SandboxRunSummary",
    "SandboxRuntimeHealthResponse",
]
