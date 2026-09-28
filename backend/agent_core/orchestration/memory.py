from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.models.agent_tasks import ScopeContext


class NullMemoryPort:
    """Explicit MA03 placeholder; M04 will provide the shared source outbox."""

    def policy_revision(self, profile_id: str) -> str:
        del profile_id
        return "memory-policy:unavailable-v1"

    def load_snapshot(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        run_id: str = "",
        temporary: bool = False,
    ) -> Mapping[str, Any]:
        del run_id, temporary
        return {
            "status": "unavailable",
            "snapshot_id": "",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
        }


__all__ = ["NullMemoryPort"]
