from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.research.workspaces import (
    ResearchWorkspace,
    ResearchWorkspaceAssociations,
    ResearchWorkspaceStore,
)


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceProfile:
    workspace: ResearchWorkspace
    document_ids: tuple[str, ...]
    note_ids: tuple[str, ...]
    conversation_ids: tuple[str, ...]

    @property
    def document_count(self) -> int:
        return len(self.document_ids)

    @property
    def note_count(self) -> int:
        return len(self.note_ids)

    @property
    def conversation_count(self) -> int:
        return len(self.conversation_ids)


class ResearchWorkspaceService:
    """Application boundary for persistent research-project context."""

    def __init__(self, store: ResearchWorkspaceStore | Any | None = None) -> None:
        self._store = store or ResearchWorkspaceStore()

    @staticmethod
    def _clean(value: object, *, limit: int) -> str:
        text = str(value or "").replace("\x00", "").strip()
        return text[:limit] if len(text) > limit else text

    def create(
        self,
        *,
        name: str,
        description: str = "",
        research_goal: str = "",
    ) -> ResearchWorkspaceProfile:
        workspace = self._store.create(
            name=self._clean(name, limit=200),
            description=self._clean(description, limit=4000),
            research_goal=self._clean(research_goal, limit=8000),
        )
        return self._profile(workspace)

    def list_recent(self, *, limit: int = 50) -> tuple[ResearchWorkspaceProfile, ...]:
        return tuple(self._profile(item) for item in self._store.list_recent(limit=limit))

    def get(self, workspace_id: str) -> ResearchWorkspaceProfile | None:
        workspace = self._store.get(workspace_id)
        return self._profile(workspace) if workspace is not None else None

    def update(
        self,
        workspace_id: str,
        *,
        name: str,
        description: str = "",
        research_goal: str = "",
    ) -> ResearchWorkspaceProfile | None:
        workspace = self._store.update(
            workspace_id,
            name=self._clean(name, limit=200),
            description=self._clean(description, limit=4000),
            research_goal=self._clean(research_goal, limit=8000),
        )
        return self._profile(workspace) if workspace is not None else None

    def delete(self, workspace_id: str) -> bool:
        return self._store.delete(workspace_id)

    def attach_document(self, workspace_id: str, document_id: str) -> bool:
        return self._store.attach(workspace_id, kind="document", resource_id=document_id)

    def detach_document(self, workspace_id: str, document_id: str) -> bool:
        return self._store.detach(workspace_id, kind="document", resource_id=document_id)

    def attach_note(self, workspace_id: str, note_id: str) -> bool:
        return self._store.attach(workspace_id, kind="note", resource_id=note_id)

    def detach_note(self, workspace_id: str, note_id: str) -> bool:
        return self._store.detach(workspace_id, kind="note", resource_id=note_id)

    def attach_conversation(self, workspace_id: str, conversation_id: str) -> bool:
        return self._store.attach(
            workspace_id,
            kind="conversation",
            resource_id=conversation_id,
        )

    def detach_conversation(self, workspace_id: str, conversation_id: str) -> bool:
        return self._store.detach(
            workspace_id,
            kind="conversation",
            resource_id=conversation_id,
        )

    def workspace_ids_for_note(self, note_id: str) -> tuple[str, ...]:
        return self._store.workspace_ids_for(kind="note", resource_id=note_id)

    def resolve_scope(self, workspace_id: str) -> ResearchWorkspaceAssociations:
        if not self._store.get(workspace_id):
            return ResearchWorkspaceAssociations()
        return self._store.associations(workspace_id)

    def _profile(self, workspace: ResearchWorkspace) -> ResearchWorkspaceProfile:
        associations = self._store.associations(workspace.workspace_id)
        return ResearchWorkspaceProfile(
            workspace=workspace,
            document_ids=associations.document_ids,
            note_ids=associations.note_ids,
            conversation_ids=associations.conversation_ids,
        )


__all__ = ["ResearchWorkspaceProfile", "ResearchWorkspaceService"]
