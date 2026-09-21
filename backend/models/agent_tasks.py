from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.agent_artifacts import ArtifactKind, ArtifactRef, EvidenceRef

MAX_TASKS_PER_PLAN = 32


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AgentTaskRecord(TaskModel):
    """Canonical user-level task that may own one or more runtime runs."""

    task_id: str = Field(min_length=1, max_length=256)
    goal: str = Field(min_length=1, max_length=20_000)
    workspace_id: str = Field(default="", max_length=256)
    created_at: datetime = Field(default_factory=utc_now)


class TaskRole(str, Enum):
    DOCUMENT = "document"
    RESEARCH = "research"
    WRITER = "writer"
    CURATOR = "curator"


class ScopeMode(str, Enum):
    """Whether an empty allow-list means global policy or no access."""

    UNSCOPED_GLOBAL = "unscoped_global"
    RESTRICTED = "restricted"


class ScopeKind(str, Enum):
    GLOBAL = "global"
    RESEARCH_WORKSPACE = "research_workspace"
    KNOWLEDGE_BOARD = "knowledge_board"
    KNOWLEDGE_COLLECTION = "knowledge_collection"
    EXPLICIT_SELECTION = "explicit_selection"


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.PARTIAL,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BLOCKED,
        TaskStatus.SKIPPED,
    }
)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class ScopeContext(TaskModel):
    scope_ref: str = Field(min_length=1, max_length=256)
    mode: ScopeMode = ScopeMode.RESTRICTED
    scope_kind: ScopeKind = ScopeKind.EXPLICIT_SELECTION
    scope_id: str = Field(default="", max_length=256)
    profile_id: str = Field(default="", max_length=256)
    workspace_id: str = Field(default="", max_length=256)
    scope_revision: str = Field(min_length=1, max_length=256)
    allowed_document_ids: list[str] = Field(default_factory=list, max_length=5000)
    allowed_note_ids: list[str] = Field(default_factory=list, max_length=5000)
    allowed_item_ids: list[str] = Field(default_factory=list, max_length=5000)
    explicit_current_source_refs: list[str] = Field(default_factory=list, max_length=1024)
    source_versions: dict[str, str] = Field(default_factory=dict)
    memory_policy_revision: str = Field(default="", max_length=256)

    @field_validator(
        "allowed_document_ids",
        "allowed_note_ids",
        "allowed_item_ids",
        "explicit_current_source_refs",
        mode="before",
    )
    @classmethod
    def normalize_ids(cls, value: Any) -> list[str]:
        values = list(value or [])
        return sorted(_dedupe_strings(values))

    @field_validator("source_versions", mode="before")
    @classmethod
    def normalize_source_versions(cls, value: Any) -> dict[str, str]:
        return {
            str(key).strip(): str(version).strip()
            for key, version in dict(value or {}).items()
            if str(key).strip()
        }

    @classmethod
    def issue(
        cls,
        *,
        profile_id: str = "",
        workspace_id: str = "",
        mode: ScopeMode | str | None = None,
        scope_kind: ScopeKind | str | None = None,
        scope_id: str = "",
        scope_revision: str,
        allowed_document_ids: list[str] | None = None,
        allowed_note_ids: list[str] | None = None,
        allowed_item_ids: list[str] | None = None,
        explicit_current_source_refs: list[str] | None = None,
        source_versions: dict[str, str] | None = None,
        memory_policy_revision: str = "",
    ) -> ScopeContext:
        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_scope_id = str(scope_id or normalized_workspace_id or "").strip()
        resolved_mode = ScopeMode(
            mode
            or (
                ScopeMode.RESTRICTED
                if normalized_scope_id
                or allowed_document_ids
                or allowed_note_ids
                or allowed_item_ids
                or explicit_current_source_refs
                else ScopeMode.UNSCOPED_GLOBAL
            )
        )
        resolved_kind = ScopeKind(
            scope_kind
            or (
                ScopeKind.RESEARCH_WORKSPACE
                if normalized_workspace_id
                else ScopeKind.GLOBAL
                if resolved_mode is ScopeMode.UNSCOPED_GLOBAL
                else ScopeKind.EXPLICIT_SELECTION
            )
        )
        payload = {
            "mode": resolved_mode,
            "scope_kind": resolved_kind,
            "scope_id": normalized_scope_id,
            "profile_id": str(profile_id or "").strip(),
            "workspace_id": normalized_workspace_id,
            "scope_revision": str(scope_revision or "").strip(),
            "allowed_document_ids": sorted(_dedupe_strings(list(allowed_document_ids or []))),
            "allowed_note_ids": sorted(_dedupe_strings(list(allowed_note_ids or []))),
            "allowed_item_ids": sorted(_dedupe_strings(list(allowed_item_ids or []))),
            "explicit_current_source_refs": sorted(
                _dedupe_strings(list(explicit_current_source_refs or []))
            ),
            "source_versions": {
                str(key).strip(): str(version).strip()
                for key, version in sorted(dict(source_versions or {}).items())
                if str(key).strip()
            },
            "memory_policy_revision": str(memory_policy_revision or "").strip(),
        }
        if not payload["scope_revision"]:
            raise ValueError("scope_revision is required")
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(scope_ref=f"scope:{digest}", **payload)


class TaskInputRef(TaskModel):
    artifact_id: str = Field(min_length=1, max_length=256)
    version: int = Field(ge=1)
    kind: ArtifactKind
    producer_task_id: str = Field(default="", max_length=256)


class TaskSpec(TaskModel):
    task_id: str = Field(min_length=1, max_length=256)
    role: TaskRole
    objective: str = Field(min_length=1, max_length=20_000)
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_TASKS_PER_PLAN)
    required: bool
    input_refs: list[TaskInputRef] = Field(default_factory=list, max_length=512)
    expected_output_kind: ArtifactKind
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=128)
    scope_ref: str = Field(min_length=1, max_length=256)
    allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    budget_ref: str = Field(default="", max_length=256)
    plan_revision: int = Field(default=1, ge=1)
    target_source_ids: list[str] = Field(default_factory=list, max_length=512)

    @field_validator(
        "depends_on",
        "allowed_tools",
        "acceptance_criteria",
        "target_source_ids",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: Any) -> list[str]:
        return _dedupe_strings(list(value or []))

    @model_validator(mode="after")
    def validate_self_dependency(self) -> TaskSpec:
        if self.task_id in self.depends_on:
            raise ValueError("task cannot depend on itself")
        return self


class ValidatedTaskPlan(TaskModel):
    plan_id: str = Field(min_length=1, max_length=256)
    plan_revision: int = Field(default=1, ge=1)
    scope_ref: str = Field(min_length=1, max_length=256)
    budget_ref: str = Field(default="", max_length=256)
    tasks: list[TaskSpec] = Field(min_length=1, max_length=MAX_TASKS_PER_PLAN)

    @model_validator(mode="after")
    def validate_graph_shape(self) -> ValidatedTaskPlan:
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")
        known = set(ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(
                    f"task {task.task_id} depends on unknown tasks: {sorted(unknown)}"
                )
            if task.plan_revision != self.plan_revision:
                raise ValueError(
                    f"task {task.task_id} plan_revision does not match plan"
                )
            if task.scope_ref != self.scope_ref:
                raise ValueError(
                    f"task {task.task_id} scope_ref does not match plan"
                )
            if self.budget_ref and task.budget_ref and task.budget_ref != self.budget_ref:
                raise ValueError(
                    f"task {task.task_id} budget_ref does not match plan"
                )

        visiting: set[str] = set()
        visited: set[str] = set()
        deps = {task.task_id: tuple(task.depends_on) for task in self.tasks}

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError("task dependency graph must be acyclic")
            visiting.add(task_id)
            for dependency in deps[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in sorted(known):
            visit(task_id)
        return self

    def task_map(self) -> dict[str, TaskSpec]:
        return {task.task_id: task for task in self.tasks}


class ResourceUsage(TaskModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    elapsed_ms: int | None = Field(default=None, ge=0)


class TaskResult(TaskModel):
    task_id: str = Field(min_length=1, max_length=256)
    attempt_id: str = Field(min_length=1, max_length=256)
    attempt_ordinal: int = Field(default=1, ge=1)
    result_version: int = Field(default=1, ge=1)
    status: TaskStatus
    artifact_refs: list[ArtifactRef] = Field(default_factory=list, max_length=512)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=512)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    unmet_requirements: list[str] = Field(default_factory=list, max_length=256)
    warnings: list[str] = Field(default_factory=list, max_length=256)
    error_code: str = Field(default="", max_length=256)
    usage: ResourceUsage = Field(default_factory=ResourceUsage)
    source_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    content_hash: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def validate_and_hash(self) -> TaskResult:
        if self.status not in TERMINAL_TASK_STATUSES:
            raise ValueError("TaskResult requires a terminal task status")
        payload = self.model_dump(
            mode="json",
            exclude={"content_hash", "usage", "started_at", "finished_at"},
        )
        expected = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("task result content_hash does not match normalized payload")
        object.__setattr__(self, "content_hash", expected)
        return self


class TaskAttemptRecord(TaskModel):
    task_id: str = Field(min_length=1, max_length=256)
    attempt_id: str = Field(min_length=1, max_length=256)
    ordinal: int = Field(ge=1)
    status: TaskStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_hash: str = Field(default="", max_length=128)
    error_code: str = Field(default="", max_length=256)


class TaskExecutionState(TaskModel):
    task_id: str = Field(min_length=1, max_length=256)
    status: TaskStatus = TaskStatus.PENDING
    attempts: list[TaskAttemptRecord] = Field(default_factory=list, max_length=128)
    current_attempt_id: str = Field(default="", max_length=256)


class WorkspaceRunState(TaskModel):
    run_id: str = Field(min_length=1, max_length=256)
    conversation_id: str = Field(default="", max_length=256)
    graph_version: str = Field(default="ma01", max_length=128)
    schema_version: int = Field(default=1, ge=1)
    scope_ref: str = Field(min_length=1, max_length=256)
    memory_snapshot_ref: str = Field(default="", max_length=256)
    plan_revision: int = Field(default=1, ge=1)
    tasks_by_id: dict[str, TaskExecutionState] = Field(default_factory=dict)
    task_results: list[TaskResult] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    budget_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    pending_commit_refs: list[str] = Field(default_factory=list)
    final_result_ref: str = Field(default="", max_length=256)


__all__ = [
    "MAX_TASKS_PER_PLAN",
    "TERMINAL_TASK_STATUSES",
    "AgentTaskRecord",
    "ResourceUsage",
    "ScopeContext",
    "ScopeKind",
    "ScopeMode",
    "TaskAttemptRecord",
    "TaskExecutionState",
    "TaskInputRef",
    "TaskResult",
    "TaskRole",
    "TaskSpec",
    "TaskStatus",
    "ValidatedTaskPlan",
    "WorkspaceRunState",
    "utc_now",
]
