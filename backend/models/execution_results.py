"""Server-issued references to sandbox output, attached to assistant messages."""

from pydantic import BaseModel, Field


class ExecutionFile(BaseModel):
    file_id: str = Field(pattern=r"^sbo_[a-f0-9]{32}$")
    relative_path: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0, le=20 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExecutionResult(BaseModel):
    sandbox_id: str = Field(pattern=r"^sb_[a-f0-9]{32}$")
    tool_call_id: str = ""
    status: str = Field(max_length=40)
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    stdout: str = Field(default="", max_length=65536)
    stderr: str = Field(default="", max_length=65536)
    logs_truncated: bool = False
    source_file_id: str = ""
    output_files: list[ExecutionFile] = Field(default_factory=list, max_length=64)
