from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from backend.models.agent_tasks import ScopeContext, ScopeKind, ScopeMode


class ScopeResolutionError(ValueError):
    """Raised when a client-selected container or member is not authoritative."""


def _ids(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value or "").strip() for value in values if str(value or "").strip()}))


class AuthoritativeScopeResolver:
    """Resolve client references through persistent server-owned memberships.

    The resolver never treats an empty restricted container as global access.  Its
    dependencies are deliberately service-shaped so tests and local deployments can
    inject the existing Research Workspace, Knowledge Workspace, and Board services.
    """

    def __init__(
        self,
        *,
        research_workspaces: Any | None = None,
        knowledge_workspace: Any | None = None,
        knowledge_boards: Any | None = None,
        research_notes: Any | None = None,
        document_exists: Callable[[str], bool] | None = None,
        source_version_resolver: Callable[[tuple[str, ...]], Mapping[str, str]] | None = None,
        global_document_ids: Iterable[str] = (),
        global_note_ids: Iterable[str] = (),
        global_item_ids: Iterable[str] = (),
    ) -> None:
        self._research_workspaces = research_workspaces
        self._knowledge_workspace = knowledge_workspace
        self._knowledge_boards = knowledge_boards
        self._research_notes = research_notes
        self._document_exists = document_exists
        self._source_version_resolver = source_version_resolver
        self._global_document_ids = _ids(global_document_ids)
        self._global_note_ids = _ids(global_note_ids)
        self._global_item_ids = _ids(global_item_ids)

    def resolve(
        self,
        *,
        profile_id: str = "",
        scope_kind: ScopeKind | str = ScopeKind.GLOBAL,
        scope_id: str = "",
        selected_document_ids: Iterable[str] = (),
        selected_note_ids: Iterable[str] = (),
        selected_item_ids: Iterable[str] = (),
        explicit_current_source_refs: Iterable[str] = (),
        memory_policy_revision: str = "",
    ) -> ScopeContext:
        kind = ScopeKind(scope_kind)
        identifier = str(scope_id or "").strip()
        requested_documents = _ids(selected_document_ids)
        requested_notes = _ids(selected_note_ids)
        requested_items = _ids(selected_item_ids)

        workspace_id = ""
        if kind is ScopeKind.GLOBAL:
            if identifier:
                raise ScopeResolutionError("global scope must not have a scope_id")
            documents = self._select(requested_documents, self._global_document_ids, "document")
            notes = self._select(requested_notes, self._global_note_ids, "note")
            items = self._select(requested_items, self._global_item_ids, "item")
            mode = ScopeMode.UNSCOPED_GLOBAL
        elif kind is ScopeKind.RESEARCH_WORKSPACE:
            if not identifier or self._research_workspaces is None:
                raise ScopeResolutionError("research workspace scope is unavailable")
            profile = self._research_workspaces.get(identifier)
            if profile is None:
                raise ScopeResolutionError("research workspace does not exist")
            workspace_id = identifier
            documents = self._select(requested_documents, _ids(profile.document_ids), "document")
            notes = self._select(requested_notes, _ids(profile.note_ids), "note")
            items = self._validate_items(requested_items)
            mode = ScopeMode.RESTRICTED
        elif kind is ScopeKind.KNOWLEDGE_BOARD:
            if not identifier or self._knowledge_boards is None:
                raise ScopeResolutionError("knowledge board scope is unavailable")
            if self._knowledge_boards.get_board(identifier) is None:
                raise ScopeResolutionError("knowledge board does not exist")
            board_items = _ids(node.item_id for node in self._knowledge_boards.list_nodes(identifier))
            items = self._select(requested_items, board_items, "item")
            documents, notes = self._resources_for_items(items)
            documents = self._select(requested_documents, documents, "document")
            notes = self._select(requested_notes, notes, "note")
            mode = ScopeMode.RESTRICTED
        elif kind is ScopeKind.KNOWLEDGE_COLLECTION:
            if not identifier or self._knowledge_workspace is None:
                raise ScopeResolutionError("knowledge collection scope is unavailable")
            getter = getattr(self._knowledge_workspace, "get_collection", None)
            if not callable(getter) or getter(identifier) is None:
                raise ScopeResolutionError("knowledge collection does not exist")
            collection_items = _ids(
                item.item_id
                for item in self._knowledge_workspace.list_items(collection_id=identifier)
            )
            items = self._select(requested_items, collection_items, "item")
            documents, notes = self._resources_for_items(items)
            documents = self._select(requested_documents, documents, "document")
            notes = self._select(requested_notes, notes, "note")
            mode = ScopeMode.RESTRICTED
        else:
            documents = self._validate_documents(requested_documents)
            notes = self._validate_notes(requested_notes)
            items = self._validate_items(requested_items)
            mode = ScopeMode.RESTRICTED

        source_ids = tuple(sorted(set(documents) | set(notes) | set(items)))
        source_versions = (
            dict(self._source_version_resolver(source_ids))
            if self._source_version_resolver is not None and source_ids
            else {}
        )
        revision_payload = {
            "kind": kind.value,
            "scope_id": identifier,
            "documents": documents,
            "notes": notes,
            "items": items,
            "versions": source_versions,
        }
        revision = hashlib.sha256(
            json.dumps(revision_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ScopeContext.issue(
            profile_id=profile_id,
            workspace_id=workspace_id,
            mode=mode,
            scope_kind=kind,
            scope_id=identifier,
            scope_revision=revision,
            allowed_document_ids=list(documents),
            allowed_note_ids=list(notes),
            allowed_item_ids=list(items),
            explicit_current_source_refs=list(_ids(explicit_current_source_refs)),
            source_versions=source_versions,
            memory_policy_revision=memory_policy_revision,
        )

    @staticmethod
    def _select(requested: tuple[str, ...], allowed: tuple[str, ...], label: str) -> tuple[str, ...]:
        if not requested:
            return allowed
        unknown = sorted(set(requested) - set(allowed))
        if unknown:
            raise ScopeResolutionError(f"{label} is outside the selected scope: {unknown[0]}")
        return requested

    def _validate_documents(self, values: tuple[str, ...]) -> tuple[str, ...]:
        if self._document_exists is None:
            return values
        for value in values:
            if not self._document_exists(value):
                raise ScopeResolutionError(f"document does not exist: {value}")
        return values

    def _validate_notes(self, values: tuple[str, ...]) -> tuple[str, ...]:
        if self._research_notes is None:
            return values
        for value in values:
            if self._research_notes.get(value) is None:
                raise ScopeResolutionError(f"research note does not exist: {value}")
        return values

    def _validate_items(self, values: tuple[str, ...]) -> tuple[str, ...]:
        if self._knowledge_workspace is None:
            return values
        for value in values:
            if self._knowledge_workspace.get_item(value) is None:
                raise ScopeResolutionError(f"knowledge item does not exist: {value}")
        return values

    def _resources_for_items(self, item_ids: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if self._knowledge_workspace is None:
            return (), ()
        documents: set[str] = set()
        notes: set[str] = set()
        for item_id in item_ids:
            item = self._knowledge_workspace.get_item(item_id)
            if item is None:
                raise ScopeResolutionError(f"knowledge item does not exist: {item_id}")
            if item.resource_document_id:
                documents.add(item.resource_document_id)
            note_id = str(item.metadata.get("research_note_id", "") or "").strip()
            if note_id:
                notes.add(note_id)
        return tuple(sorted(documents)), tuple(sorted(notes))


__all__ = ["AuthoritativeScopeResolver", "ScopeResolutionError"]
