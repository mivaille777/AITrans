from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from backend.models.agent_artifacts import Artifact, EvidenceRef
from backend.models.agent_tasks import ScopeContext, TaskSpec


@runtime_checkable
class MemoryPort(Protocol):
    def load_snapshot(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        run_id: str = "",
        temporary: bool = False,
    ) -> Mapping[str, Any]:
        ...


@runtime_checkable
class EvidencePort(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        scope: ScopeContext,
        limit: int,
    ) -> tuple[EvidenceRef, ...]:
        ...


@runtime_checkable
class ToolRuntimePort(Protocol):
    def execute(
        self,
        *,
        task: TaskSpec,
        tool_name: str,
        arguments: Mapping[str, Any],
        scope: ScopeContext,
    ) -> Mapping[str, Any]:
        ...


@runtime_checkable
class ArtifactPort(Protocol):
    def put(self, artifact: Artifact) -> Artifact:
        ...

    def get(
        self,
        artifact_id: str,
        version: int,
        *,
        include_revoked: bool = False,
    ) -> Artifact | None:
        ...

    def list_versions(
        self,
        artifact_id: str,
        *,
        include_revoked: bool = False,
    ) -> tuple[Artifact, ...]:
        ...

    def revoke(
        self,
        artifact_id: str,
        version: int,
        *,
        reason: str,
    ) -> bool:
        ...

    def migrate(self, target_version: int | None = None) -> int:
        ...


@runtime_checkable
class BudgetPort(Protocol):
    def reserve(
        self,
        *,
        budget_ref: str,
        task_id: str,
        resource: str,
        amount: int,
    ) -> bool:
        ...

    def record(
        self,
        *,
        budget_ref: str,
        task_id: str,
        usage: Mapping[str, int | None],
    ) -> None:
        ...


__all__ = [
    "ArtifactPort",
    "BudgetPort",
    "EvidencePort",
    "MemoryPort",
    "ToolRuntimePort",
]
