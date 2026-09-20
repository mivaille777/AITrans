from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agent_core.multi_agent.context import KnowledgeInjector, SharedAgentContext
from backend.agent_core.orchestration.evidence_service import ScopedEvidenceService
from backend.agent_core.orchestration.scope_resolver import (
    AuthoritativeScopeResolver,
    ScopeResolutionError,
)
from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType
from backend.models.agent_tasks import ScopeContext, ScopeKind, ScopeMode


class WorkspaceService:
    def __init__(self) -> None:
        self.profiles = {
            "workspace-a": SimpleNamespace(
                document_ids=("doc-a",), note_ids=("note-a",), conversation_ids=()
            )
        }

    def get(self, workspace_id: str):
        return self.profiles.get(workspace_id)


class Notes:
    def __init__(self) -> None:
        self.items = {
            "note-a": SimpleNamespace(
                note_id="note-a",
                fingerprint="hash-a",
                source_text="alpha result",
                translated_text="",
                ai_content="",
                user_note="",
                resource_url="file:///a.pdf",
                section_heading="Results",
                display_title="Paper A",
            ),
            "note-b": SimpleNamespace(
                note_id="note-b",
                fingerprint="hash-b",
                source_text="alpha private result",
                translated_text="",
                ai_content="",
                user_note="",
                resource_url="file:///b.pdf",
                section_heading="Results",
                display_title="Paper B",
            ),
        }
        self.calls: list[tuple[str, ...]] = []

    def get(self, note_id: str):
        return self.items.get(note_id)

    def search(self, query: str, *, limit: int, note_ids: list[str]):
        del query, limit
        self.calls.append(tuple(note_ids))
        # Simulate an over-broad repository response. The evidence service must
        # still enforce the exact trusted note IDs on the final packet list.
        return tuple(
            SimpleNamespace(note=item, score=1.0)
            for item in self.items.values()
        )


class Knowledge:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.items = {
            "item-a": KnowledgeItem(
                item_id="item-a",
                item_type=KnowledgeItemType.PAPER,
                title="Paper A",
                resource_document_id="doc-a",
                metadata={"research_note_id": "note-a"},
                updated_at=now,
            ),
            "item-b": KnowledgeItem(
                item_id="item-b",
                item_type=KnowledgeItemType.CONCEPT,
                title="Private B",
                resource_document_id="doc-b",
                updated_at=now,
            ),
        }

    def get_item(self, item_id: str):
        return self.items.get(item_id)

    def list_items(self, *, collection_id: str | None = None):
        if collection_id == "collection-a":
            return [self.items["item-a"]]
        return list(self.items.values())

    def get_collection(self, collection_id: str):
        return SimpleNamespace(collection_id=collection_id) if collection_id == "collection-a" else None

    def list_relations(self):
        return []


class Boards:
    def get_board(self, board_id: str):
        return SimpleNamespace(board_id=board_id) if board_id == "board-a" else None

    def list_nodes(self, board_id: str):
        return [SimpleNamespace(item_id="item-a")] if board_id == "board-a" else []


def test_scope_context_distinguishes_global_from_restricted_empty() -> None:
    global_scope = ScopeContext.issue(scope_revision="g")
    empty_scope = ScopeContext.issue(
        scope_revision="e",
        mode=ScopeMode.RESTRICTED,
        scope_kind=ScopeKind.RESEARCH_WORKSPACE,
        scope_id="empty-workspace",
        workspace_id="empty-workspace",
    )

    assert global_scope.mode is ScopeMode.UNSCOPED_GLOBAL
    assert empty_scope.mode is ScopeMode.RESTRICTED
    assert empty_scope.allowed_document_ids == []
    assert global_scope.scope_ref != empty_scope.scope_ref


def test_authoritative_scope_resolver_uses_persisted_memberships() -> None:
    resolver = AuthoritativeScopeResolver(
        research_workspaces=WorkspaceService(),
        research_notes=Notes(),
        document_exists=lambda document_id: document_id == "doc-a",
    )

    scope = resolver.resolve(
        profile_id="profile-1",
        scope_kind=ScopeKind.RESEARCH_WORKSPACE,
        scope_id="workspace-a",
    )

    assert scope.workspace_id == "workspace-a"
    assert scope.allowed_document_ids == ["doc-a"]
    assert scope.allowed_note_ids == ["note-a"]
    assert scope.mode is ScopeMode.RESTRICTED

    with pytest.raises(ScopeResolutionError, match="outside"):
        resolver.resolve(
            scope_kind=ScopeKind.RESEARCH_WORKSPACE,
            scope_id="workspace-a",
            selected_note_ids=["note-b"],
        )


@pytest.mark.parametrize(
    ("kind", "scope_id"),
    [
        (ScopeKind.KNOWLEDGE_BOARD, "board-a"),
        (ScopeKind.KNOWLEDGE_COLLECTION, "collection-a"),
    ],
)
def test_board_and_collection_resolve_item_document_and_note_scope(kind, scope_id) -> None:
    resolver = AuthoritativeScopeResolver(
        knowledge_workspace=Knowledge(),
        knowledge_boards=Boards(),
    )

    scope = resolver.resolve(scope_kind=kind, scope_id=scope_id)

    assert scope.allowed_item_ids == ["item-a"]
    assert scope.allowed_document_ids == ["doc-a"]
    assert scope.allowed_note_ids == ["note-a"]


def test_restricted_empty_scope_returns_no_evidence_and_does_not_query_backends() -> None:
    notes = Notes()
    service = ScopedEvidenceService(research_notes=notes)
    scope = ScopeContext.issue(
        scope_revision="empty",
        mode=ScopeMode.RESTRICTED,
        scope_kind=ScopeKind.RESEARCH_WORKSPACE,
        scope_id="workspace-empty",
        workspace_id="workspace-empty",
    )

    assert service.retrieve_packets(query="alpha", scope=scope) == ()
    assert notes.calls == []


def test_exact_note_ids_are_rechecked_after_repository_search() -> None:
    notes = Notes()
    service = ScopedEvidenceService(research_notes=notes)
    scope = ScopeContext.issue(
        scope_revision="workspace-a-r1",
        workspace_id="workspace-a",
        allowed_note_ids=["note-a"],
    )

    packets = service.retrieve_packets(query="alpha", scope=scope)

    assert notes.calls == [("note-a",)]
    assert [packet.evidence_ref.source_id for packet in packets] == ["note-a"]


def test_injector_uses_scoped_evidence_packets_instead_of_legacy_graph() -> None:
    notes = Notes()
    service = ScopedEvidenceService(research_notes=notes)

    class LegacyRuntime:
        def build_context(self, *_args, **_kwargs):
            raise AssertionError("legacy whole-graph runtime must not be called")

    scope = ScopeContext.issue(
        scope_revision="workspace-a-r1",
        workspace_id="workspace-a",
        allowed_note_ids=["note-a"],
    )
    context = SharedAgentContext(query="alpha", runtime={"scope_context": scope})

    KnowledgeInjector(LegacyRuntime(), evidence_service=service).inject("alpha", context)

    assert "note:note-a" in context.knowledge_context
    assert all(item["source_id"] == "note-a" for item in context.citations)
