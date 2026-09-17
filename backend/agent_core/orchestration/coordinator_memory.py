from __future__ import annotations

from typing import Any

from backend.models.agent_tasks import ScopeContext


def role_memory_projection(snapshot: Any, role: str) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    projections = snapshot.get("role_projections", {})
    if not isinstance(projections, dict):
        return []
    values = projections.get(role, [])
    return [dict(item) for item in values if isinstance(item, dict)][:32]


class CoordinatorMemoryPort:
    def __init__(self, coordinator: Any, *, artifact_store: Any | None = None) -> None:
        self.coordinator = coordinator
        self.artifact_store = artifact_store

    def load_snapshot(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        run_id: str = "",
        temporary: bool = False,
    ) -> dict[str, Any]:
        return self.coordinator.load_snapshot(
            profile_id=profile_id,
            scope=scope,
            run_id=run_id,
            temporary=temporary,
        )

    def submit_candidates(
        self,
        *,
        profile_id: str,
        workspace_id: str,
        artifact_refs: list[Any],
        temporary: bool = False,
        scope_ref: str = "",
    ) -> tuple[Any, ...]:
        if temporary or self.artifact_store is None:
            return ()
        pending = getattr(self.artifact_store, "pending_memory_refs", None)
        refs = list(pending(limit=1000)) if callable(pending) and scope_ref else []
        refs.extend(artifact_refs)
        unique_refs = {
            (ref.artifact_id, ref.version, ref.content_hash): ref for ref in refs
        }
        mark_delivered = getattr(self.artifact_store, "mark_memory_delivered", None)
        saved: list[Any] = []
        for ref in unique_refs.values():
            artifact = self.artifact_store.get(ref.artifact_id, ref.version)
            if (
                artifact is not None
                and scope_ref
                and artifact.scope_ref != scope_ref
                and ref not in artifact_refs
            ):
                continue
            if artifact is not None and artifact.content_hash == ref.content_hash:
                saved.extend(
                    self.coordinator.submit_artifact_candidates(
                        profile_id=profile_id,
                        workspace_id=workspace_id,
                        artifacts=[artifact],
                        temporary=temporary,
                    )
                )
            if callable(mark_delivered):
                mark_delivered(ref)
        return tuple(saved)


__all__ = ["CoordinatorMemoryPort", "role_memory_projection"]
