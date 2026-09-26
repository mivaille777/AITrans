"""Typed sandbox requests, results, and health information."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class SandboxExecutionRequest(SandboxModel):
    sandbox_id: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=50_000)


class SandboxOutputFile(SandboxModel):
    file_id: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class SandboxExecutionResult(SandboxModel):
    sandbox_id: str = Field(min_length=1, max_length=80)
    status: Literal[
        "succeeded",
        "failed",
        "timed_out",
        "oom_killed",
        "output_limit_exceeded",
    ]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    timed_out: bool = False
    output_limit_exceeded: bool = False
    oom_killed: bool = False
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    runtime: str = "docker"
    image: str = ""
    output_files: list[SandboxOutputFile] = Field(default_factory=list)


class SandboxRuntimeHealth(SandboxModel):
    available: bool
    runtime: str = "docker"
    image: str = ""
    server_os: str = ""
    error_code: str | None = None
    message: str = ""
