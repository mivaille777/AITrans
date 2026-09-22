from __future__ import annotations

from collections.abc import Iterable

from backend.models.knowledge_access import (
    KnowledgeScopeStrategy,
    ResolvedKnowledgeScope,
)


EMPTY_WORKSPACE_SCOPE_PREFIX = "__workspace_empty_scope__"


def empty_workspace_scope_id(workspace_id: str, kind: str) -> str:
    """Return the closed-world sentinel used by retrieval tools."""

    normalized_workspace = str(workspace_id or "").strip()
    normalized_kind = str(kind or "").strip().lower()
    if not normalized_workspace:
        raise ValueError("workspace_id is required for an empty workspace scope")
    if normalized_kind not in {"document", "research"}:
        raise ValueError("empty workspace scope kind must be document or research")
    return f"{EMPTY_WORKSPACE_SCOPE_PREFIX}:{normalized_kind}:{normalized_workspace}"


def _ids(values: Iterable[object] | None) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        identifier = str(raw or "").strip()
        if not identifier or identifier in seen:
            continue
        result.append(identifier)
        seen.add(identifier)
    return tuple(result)


class KnowledgeScopeResolver:
    """Resolve retrieval scope without conflating it with retrieval intent.

    ``workspace_id`` represents an active Research Workspace, not an automatic
    command to search it. Reading requests prefer their attached document unless
    the caller explicitly selects document IDs. The optional legacy fallback is
    kept only for pre-contract requests that supplied a workspace and the old
    ``knowledge_document_ids`` field without an attached document ID.
    """

    def resolve(
        self,
        *,
        context_mode: str,
        explicit_document_ids: Iterable[object] | None = None,
        attached_document_id: str = "",
        workspace_id: str = "",
        workspace_document_ids: Iterable[object] | None = None,
        research_source_ids: Iterable[object] | None = None,
        global_allowed: bool = False,
        requested_strategy: str | KnowledgeScopeStrategy | None = None,
        legacy_workspace_fallback: bool = False,
    ) -> ResolvedKnowledgeScope:
        mode = str(context_mode or "general").strip().lower()
        explicit = _ids(explicit_document_ids)
        attached = str(attached_document_id or "").strip()
        workspace = str(workspace_id or "").strip()
        workspace_documents = _ids(workspace_document_ids)
        research_sources = _ids(research_source_ids)
        requested = (
            KnowledgeScopeStrategy(requested_strategy)
            if requested_strategy
            else None
        )

        if explicit:
            return ResolvedKnowledgeScope(
                strategy=KnowledgeScopeStrategy.EXPLICIT_DOCUMENTS,
                document_ids=explicit,
                reason="Explicit document scope is the highest-priority access boundary.",
            )

        if requested is KnowledgeScopeStrategy.RESEARCH_WORKSPACE and workspace:
            return self._workspace_scope(
                workspace,
                workspace_documents,
                research_sources,
                reason="The knowledge decision explicitly selected the Research Workspace.",
            )

        if mode == "research" and workspace:
            return self._workspace_scope(
                workspace,
                workspace_documents,
                research_sources,
                reason="Research tasks are restricted to the active Research Workspace.",
            )

        if attached:
            return ResolvedKnowledgeScope(
                strategy=KnowledgeScopeStrategy.ATTACHED_DOCUMENT,
                document_ids=(attached,),
                reason="The attached Reading document is the preferred scope for this task.",
            )

        if legacy_workspace_fallback and workspace:
            return self._workspace_scope(
                workspace,
                workspace_documents,
                research_sources,
                reason="Legacy request preserved its explicit workspace boundary.",
            )

        if requested is KnowledgeScopeStrategy.GLOBAL_KNOWLEDGE or global_allowed:
            return ResolvedKnowledgeScope(
                strategy=KnowledgeScopeStrategy.GLOBAL_KNOWLEDGE,
                allow_global=True,
                reason="Global Knowledge access was explicitly allowed by the request.",
            )

        return ResolvedKnowledgeScope(
            strategy=KnowledgeScopeStrategy.NONE,
            reason="No valid document or Research Workspace scope was selected.",
        )

    @staticmethod
    def _workspace_scope(
        workspace_id: str,
        document_ids: tuple[str, ...],
        research_source_ids: tuple[str, ...],
        *,
        reason: str,
    ) -> ResolvedKnowledgeScope:
        return ResolvedKnowledgeScope(
            strategy=KnowledgeScopeStrategy.RESEARCH_WORKSPACE,
            document_ids=document_ids or (empty_workspace_scope_id(workspace_id, "document"),),
            workspace_id=workspace_id,
            research_source_ids=research_source_ids
            or (empty_workspace_scope_id(workspace_id, "research"),),
            allow_global=False,
            reason=reason,
        )


__all__ = [
    "EMPTY_WORKSPACE_SCOPE_PREFIX",
    "KnowledgeScopeResolver",
    "empty_workspace_scope_id",
]
