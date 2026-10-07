"""Public management views; executor contracts remain owned by typed tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ManagementModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolSummary(ManagementModel):
    tool_id: str
    name: str
    title: str
    description: str
    category: str
    namespace: str = "agent"
    origin: Literal["builtin", "custom"] = "builtin"
    effect: Literal["read", "compute", "write"]
    enabled: bool = True
    available: bool = True
    effective_enabled: bool = True
    unavailable_reason: str = ""
    risk_level: str = "unknown"


class ToolDetail(ToolSummary):
    tool_version: str
    revision: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    input_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context_requirements: list[str] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    execution_capabilities: dict[str, bool] = Field(default_factory=dict)
    editable_fields: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class ToolCatalog(ManagementModel):
    items: list[ToolSummary]
    categories: dict[str, int]
    total: int
    enabled: int
    disabled: int
    matched_total: int
    next_cursor: str | None = None
    catalog_revision: str


class ToolUpdate(ManagementModel):
    revision: str
    enabled: StrictBool
