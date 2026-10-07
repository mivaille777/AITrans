"""Untrusted test input and server-owned execution envelope."""

from typing import Any

from pydantic import Field, StrictBool

from backend.models.tool_management import ManagementModel


class ToolContextSelection(ManagementModel):
    research_workspace_id: str = Field(default="", max_length=128)
    filesystem_workspace_id: str = Field(default="", max_length=128)
    knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)
    reading_context: dict[str, Any] = Field(default_factory=dict)


class ToolTestRequest(ManagementModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    context_selection: ToolContextSelection = Field(
        default_factory=ToolContextSelection
    )
    timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    stream_output: StrictBool = False
    client_request_id: str = Field(min_length=1, max_length=128)


class ToolTestRun(ManagementModel):
    test_run_id: str
    tool_id: str
    tool_name: str
    trace_id: str
    tool_call_id: str
    status: str = "queued"
    execution_state: str = "not_started"
    created_at: str
    updated_at: str
    finished_at: str | None = None
    elapsed_ms: int = 0
    result: dict[str, Any] | None = None
    result_truncated: bool = False
    error: dict[str, Any] | None = None
    approval_id: str | None = None
    approval_summary: dict[str, Any] | None = None


class ToolTestApproval(ManagementModel):
    approval_id: str = Field(min_length=1, max_length=128)
