from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.memory.repository import MemoryConflictError, SQLiteMemoryRepository
from backend.models.agent_artifacts import Artifact, VerificationStatus
from backend.models.agent_tasks import ScopeContext
from backend.models.memory import (
    MemoryCandidate,
    MemoryItem,
    MemoryKind,
    MemoryPacket,
    MemoryReference,
    MemoryStatus,
)

_ROLE_BY_KIND: dict[MemoryKind, tuple[str, ...]] = {
    MemoryKind.READING_GOAL: ("document", "research"),
    MemoryKind.RESEARCH_DECISION: ("research", "writer", "curator"),
    MemoryKind.WRITING_STYLE: ("writer", "language"),
    MemoryKind.TERMINOLOGY: ("document", "research", "writer", "curator", "language"),
    MemoryKind.CURATION_PREFERENCE: ("curator",),
    MemoryKind.PROJECT_REFERENCE: ("document", "research", "writer", "curator"),
}


class MemoryCoordinator:
    """One canonical memory boundary for scoped snapshots and candidates."""

    def __init__(self, repository: SQLiteMemoryRepository) -> None:
        self.repository = repository

    def remember(
        self,
        *,
        operation_id: str,
        profile_id: str,
        kind: MemoryKind,
        content: str,
        source_ref: str,
        workspace_id: str = "",
        audience: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        item_id: str = "",
        expected_version: int = 0,
    ) -> MemoryItem:
        return self.repository.save(
            operation_id=operation_id,
            profile_id=profile_id,
            workspace_id=workspace_id,
            kind=kind,
            content=content,
            source_type="explicit_user",
            source_ref=source_ref,
            audience=list(audience or _ROLE_BY_KIND[kind]),
            metadata=dict(metadata or {}),
            status=MemoryStatus.ACTIVE,
            item_id=item_id,
            expected_version=expected_version,
        )

    def submit_candidate(self, candidate: MemoryCandidate) -> MemoryItem:
        return self.repository.save(
            operation_id=candidate.operation_id,
            profile_id=candidate.profile_id,
            workspace_id=candidate.workspace_id,
            kind=candidate.kind,
            content=candidate.content,
            source_type="verified_artifact",
            source_ref=candidate.source_ref,
            audience=candidate.audience or list(_ROLE_BY_KIND[candidate.kind]),
            metadata=candidate.metadata,
            status=MemoryStatus.CANDIDATE,
        )

    def update(
        self,
        *,
        operation_id: str,
        profile_id: str,
        item_id: str,
        expected_version: int,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        activate: bool = False,
    ) -> MemoryItem:
        current = self.repository.get(item_id)
        if current is None or current.profile_id != profile_id:
            raise ValueError("memory item not found")
        if activate and current.status is not MemoryStatus.CANDIDATE:
            raise ValueError("only a candidate memory can be activated")
        return self.repository.save(
            operation_id=operation_id,
            profile_id=profile_id,
            workspace_id=current.workspace_id,
            kind=current.kind,
            content=str(content).strip() if content is not None else current.content,
            source_type=current.source_type,
            source_ref=current.source_ref,
            audience=current.audience,
            metadata=dict(metadata) if metadata is not None else current.metadata,
            status=MemoryStatus.ACTIVE if activate else current.status,
            item_id=current.item_id,
            expected_version=expected_version,
        )

    def list_items(
        self,
        *,
        profile_id: str,
        workspace_id: str | None = None,
        status: MemoryStatus | None = None,
    ) -> tuple[MemoryItem, ...]:
        return self.repository.list_items(
            profile_id=profile_id,
            workspace_id=workspace_id,
            status=status,
        )

    def forget(
        self, *, profile_id: str, item_id: str, expected_version: int
    ) -> MemoryItem:
        return self.repository.revoke(
            profile_id=profile_id,
            item_id=item_id,
            expected_version=expected_version,
        )

    @staticmethod
    def _packet(
        *,
        status: str,
        snapshot_id: str,
        profile_id: str,
        scope: ScopeContext,
        items: tuple[MemoryItem, ...],
        reason_code: str = "",
    ) -> MemoryPacket:
        projections: dict[str, list[dict[str, Any]]] = defaultdict(list)
        invalidated: list[str] = []
        references: list[MemoryReference] = []
        for item in items:
            if item.status is not MemoryStatus.ACTIVE:
                invalidated.append(item.item_id)
                continue
            if item.workspace_id and item.workspace_id != scope.workspace_id:
                invalidated.append(item.item_id)
                continue
            references.append(
                MemoryReference(
                    item_id=item.item_id,
                    version=item.version,
                    kind=item.kind,
                    workspace_id=item.workspace_id,
                    content_hash=item.content_hash,
                )
            )
            payload = {
                "item_id": item.item_id,
                "version": item.version,
                "kind": item.kind.value,
                "content": item.content,
                "source_ref": item.source_ref,
                "metadata": item.metadata,
            }
            for role in item.audience or _ROLE_BY_KIND[item.kind]:
                projections[role].append(payload)
        resolved_status = "invalidated" if invalidated else status
        return MemoryPacket(
            status=resolved_status,
            snapshot_id=snapshot_id,
            profile_id=profile_id,
            scope_ref=scope.scope_ref,
            workspace_id=scope.workspace_id,
            references=references,
            role_projections=dict(projections),
            invalidated_item_ids=invalidated,
            reason_code="snapshot_item_revoked_or_out_of_scope"
            if invalidated
            else reason_code,
        )

    def load_snapshot(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        run_id: str = "",
        temporary: bool = False,
    ) -> dict[str, Any]:
        if temporary:
            return MemoryPacket(
                status="temporary",
                profile_id=profile_id,
                scope_ref=scope.scope_ref,
                workspace_id=scope.workspace_id,
                reason_code="temporary_memory_disabled",
            ).model_dump(mode="json")
        stable_run_id = str(run_id).strip() or f"snapshot:{scope.scope_ref}"
        try:
            snapshot_id, items = self.repository.snapshot_for_run(
                run_id=stable_run_id,
                profile_id=profile_id,
                workspace_id=scope.workspace_id,
                scope_ref=scope.scope_ref,
            )
        except MemoryConflictError:
            return MemoryPacket(
                status="invalidated",
                profile_id=profile_id,
                scope_ref=scope.scope_ref,
                workspace_id=scope.workspace_id,
                reason_code="snapshot_scope_changed",
            ).model_dump(mode="json")
        # Snapshot versions remain frozen across ordinary updates, but a current
        # tombstone or workspace mismatch invalidates the old body immediately.
        checked: list[MemoryItem] = []
        for item in items:
            current = self.repository.get(item.item_id)
            checked.append(
                item.model_copy(update={"status": current.status})
                if current is not None
                else item.model_copy(update={"status": MemoryStatus.REVOKED})
            )
        packet = self._packet(
            status="ready" if checked else "empty",
            snapshot_id=snapshot_id,
            profile_id=profile_id,
            scope=scope,
            items=tuple(checked),
        )
        return packet.model_dump(mode="json")

    def submit_artifact_candidates(
        self,
        *,
        profile_id: str,
        workspace_id: str,
        artifacts: list[Artifact],
        temporary: bool = False,
    ) -> tuple[MemoryItem, ...]:
        if temporary:
            return ()
        saved: list[MemoryItem] = []
        for artifact in artifacts:
            if artifact.verification_status is not VerificationStatus.PASSED:
                continue
            for claim in artifact.claims:
                if not claim.evidence_ids or claim.category == "user_supplied":
                    continue
                saved.append(
                    self.submit_candidate(
                        MemoryCandidate(
                            operation_id=f"artifact:{artifact.artifact_id}:{artifact.version}:{claim.claim_id}",
                            profile_id=profile_id,
                            workspace_id=workspace_id,
                            kind=MemoryKind.RESEARCH_DECISION,
                            content=claim.statement,
                            source_ref=f"artifact:{artifact.artifact_id}:{artifact.version}",
                            audience=["research", "writer", "curator"],
                            metadata={
                                "claim_id": claim.claim_id,
                                "evidence_ids": list(claim.evidence_ids),
                                "artifact_hash": artifact.content_hash,
                            },
                        )
                    )
                )
        return tuple(saved)


__all__ = ["MemoryCoordinator"]
