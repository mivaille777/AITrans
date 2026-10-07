"""Versioned data-only presets; no imported executable capabilities."""

from typing import Any, Literal

from pydantic import Field, StrictInt

from backend.models.tool_management import ManagementModel


class ToolMetadata(ManagementModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    defaults: dict[str, Any] | None = None
    examples: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120, strict=True)


class CustomToolPreset(ManagementModel):
    name: str = Field(pattern=r"^custom_[a-z][a-z0-9_]{2,63}$")
    template_id: Literal["builtin:search_knowledge_base"] = (
        "builtin:search_knowledge_base"
    )
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    fixed_arguments: dict[str, Any] = Field(default_factory=dict)
    exposed_fields: list[str] = Field(
        default_factory=lambda: ["query", "document_scope", "document_ids", "top_k"],
        max_length=32,
    )
    defaults: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    timeout_seconds: int = Field(default=20, ge=1, le=120, strict=True)


class ToolImportDocument(ManagementModel):
    schema_version: StrictInt = 1
    tools: list[CustomToolPreset] = Field(min_length=1, max_length=100)


class ToolImportRequest(ManagementModel):
    document: ToolImportDocument
    preview_token: str = Field(min_length=1, max_length=128)
    conflict_mode: Literal["reject", "replace"] = "reject"


class ToolArchiveRequest(ManagementModel):
    revision: str
