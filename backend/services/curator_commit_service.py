from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from backend.knowledge.domain import (
    AI_SUGGESTIBLE_RELATION_TYPES,
    KnowledgeItemType,
    KnowledgeRelationSuggestion,
)
from backend.models.agent_artifacts import (
    KnowledgeDraftArtifact,
    KnowledgeItemDraft,
    NoteDraft,
)
from backend.models.agent_tasks import ScopeContext, ScopeMode
from backend.models.curator_commit import (
    CuratorCommitReceipt,
    CuratorCommitTargetResult,
)


class CuratorCommitError(ValueError):
    pass


class CuratorCommitConflictError(CuratorCommitError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def research_note_content_hash(note: Any) -> str:
    return _hash(
        {
            "note_id": str(getattr(note, "note_id", "")),
            "source_text": str(getattr(note, "source_text", "")),
            "ai_content": str(getattr(note, "ai_content", "")),
            "user_note": str(getattr(note, "user_note", "")),
            "updated_at": str(getattr(note, "updated_at", "")),
        }
    )


def knowledge_item_content_hash(item: Any) -> str:
    return _hash(
        {
            "item_id": str(getattr(item, "item_id", "")),
            "item_type": str(
                getattr(
                    getattr(item, "item_type", ""),
                    "value",
                    getattr(item, "item_type", ""),
                )
            ),
            "title": str(getattr(item, "title", "")),
            "summary": str(getattr(item, "summary", "")),
            "resource_document_id": getattr(item, "resource_document_id", None),
            "source_uri": str(getattr(item, "source_uri", "")),
            "metadata": dict(getattr(item, "metadata", {}) or {}),
            "updated_at": str(getattr(item, "updated_at", "")),
        }
    )


class CuratorCommitService:
    """Apply an approved KnowledgeDraft through existing canonical stores.

    Research notes and canonical knowledge objects live in separate SQLite
    stores. The operation receipt therefore records explicit steps and stable
    deterministic object IDs; it never claims a cross-database transaction.
    """

    def __init__(
        self,
        *,
        artifact_store: Any,
        knowledge_workspace: Any,
        suggestion_repository: Any,
        research_notes: Any,
        research_workspaces: Any | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        repository = getattr(knowledge_workspace, "_repository", None)
        inferred = getattr(repository, "storage_path", None)
        if database_path is None and inferred is None:
            raise ValueError("database_path is required for curator commit receipts")
        self.database_path = Path(database_path or inferred).expanduser().resolve()
        self._artifacts = artifact_store
        self._knowledge = knowledge_workspace
        self._suggestions = suggestion_repository
        self._notes = research_notes
        self._workspaces = research_workspaces
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS curator_commit_operations (
                    operation_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_version INTEGER NOT NULL,
                    workspace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(status IN ('in_progress', 'completed', 'partial', 'failed'))
                );
                """
            )

    @staticmethod
    def _payload_hash(
        *,
        artifact: KnowledgeDraftArtifact,
        scope: ScopeContext,
        selected_draft_ids: set[str],
    ) -> str:
        return _hash(
            {
                "artifact_ref": artifact.ref().model_dump(mode="json"),
                "scope_ref": scope.scope_ref,
                "workspace_id": artifact.workspace_id,
                "selected_draft_ids": sorted(selected_draft_ids),
            }
        )

    def get_receipt(self, operation_id: str) -> CuratorCommitReceipt | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT receipt_json FROM curator_commit_operations WHERE operation_id = ?",
                (str(operation_id).strip(),),
            ).fetchone()
        return (
            CuratorCommitReceipt.model_validate_json(str(row["receipt_json"]))
            if row
            else None
        )

    def _save_receipt(self, receipt: CuratorCommitReceipt) -> CuratorCommitReceipt:
        now = _now()
        persisted = receipt.model_copy(update={"replayed": False})
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO curator_commit_operations(
                    operation_id, payload_hash, artifact_id, artifact_version,
                    workspace_id, status, receipt_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    status=excluded.status,
                    receipt_json=excluded.receipt_json,
                    updated_at=excluded.updated_at
                """,
                (
                    persisted.operation_id,
                    persisted.payload_hash,
                    persisted.artifact_id,
                    persisted.artifact_version,
                    persisted.workspace_id,
                    persisted.status,
                    persisted.model_dump_json(),
                    now,
                    now,
                ),
            )
        return persisted

    @staticmethod
    def _stable_id(prefix: str, operation_id: str, target_key: str) -> str:
        digest = hashlib.sha256(f"{operation_id}\0{target_key}".encode()).hexdigest()
        return f"{prefix}_{digest[:32]}"

    def _validate_scope(
        self, artifact: KnowledgeDraftArtifact, scope: ScopeContext
    ) -> None:
        workspace_id = scope.workspace_id or scope.scope_id
        if artifact.scope_ref != scope.scope_ref:
            raise CuratorCommitConflictError(
                "artifact scope is stale or no longer authorized"
            )
        if not workspace_id or artifact.workspace_id != workspace_id:
            raise CuratorCommitError(
                "artifact workspace does not match the authorized workspace"
            )
        if self._workspaces is not None and self._workspaces.get(workspace_id) is None:
            raise CuratorCommitError("research workspace no longer exists")

    def _validate_sources(self, source_ids: list[str], scope: ScopeContext) -> None:
        if scope.mode is ScopeMode.UNSCOPED_GLOBAL:
            return
        allowed = (
            set(scope.allowed_document_ids)
            | set(scope.allowed_note_ids)
            | set(scope.allowed_item_ids)
            | set(scope.explicit_current_source_refs)
        )
        unknown = set(source_ids) - allowed
        if unknown:
            raise CuratorCommitError(
                f"source is no longer authorized: {sorted(unknown)}"
            )

    def _commit_note(
        self,
        *,
        operation_id: str,
        artifact: KnowledgeDraftArtifact,
        draft: NoteDraft,
        scope: ScopeContext,
    ) -> tuple[str, str]:
        if draft.user_note:
            raise CuratorCommitError("AI note drafts cannot write user_note")
        self._validate_sources([draft.source_id], scope)
        if draft.existing_note_id:
            if draft.expected_version != 1 or not draft.expected_content_hash:
                raise CuratorCommitConflictError(
                    "existing research note requires expected_version=1 and a content hash"
                )
            current = self._notes.get(draft.existing_note_id)
            if current is None:
                raise CuratorCommitConflictError(
                    "target research note no longer exists"
                )
            if (
                draft.expected_content_hash
                and research_note_content_hash(current) != draft.expected_content_hash
            ):
                raise CuratorCommitConflictError(
                    "research note changed after the draft was prepared"
                )
            if current.source_text != draft.source_quote:
                raise CuratorCommitConflictError(
                    "research note source quote cannot be replaced"
                )
        elif draft.expected_version != 0 or draft.expected_content_hash:
            raise CuratorCommitConflictError(
                "new research note must use expected_version=0 without a content hash"
            )
        result = self._notes.save(
            source_text=draft.source_quote,
            resource_url=draft.resource_uri,
            resource_title=draft.resource_title,
            section_heading=draft.section_heading,
            source_kind="agent_curator",
            ai_content=draft.ai_content,
            ai_action="knowledge_curator",
            user_note="",
            workspace_id=artifact.workspace_id,
        )
        note_id = result.note.note_id
        item_key = f"note-item:{draft.draft_id}"
        item_id = self._stable_id("ki", operation_id, item_key)
        existing = self._knowledge.get_item(item_id)
        if existing is None:
            self._knowledge.create_item(
                item_id=item_id,
                item_type=KnowledgeItemType.NOTE,
                title=draft.resource_title
                or draft.section_heading
                or draft.ai_content[:120]
                or "Research note",
                summary=draft.ai_content,
                resource_document_id=draft.source_id
                if draft.source_id in scope.allowed_document_ids
                else None,
                source_uri=draft.resource_uri,
                metadata={
                    "workspace_id": artifact.workspace_id,
                    "research_note_id": note_id,
                    "source_id": draft.source_id,
                    "source_quote_hash": _hash(draft.source_quote),
                    "ai_content_hash": _hash(draft.ai_content),
                    "provenance": "knowledge_curator",
                },
            )
        return note_id, item_id

    def _commit_item(
        self,
        *,
        operation_id: str,
        artifact: KnowledgeDraftArtifact,
        draft: KnowledgeItemDraft,
        scope: ScopeContext,
    ) -> str:
        if draft.user_note:
            raise CuratorCommitError("AI item drafts cannot write user_note")
        self._validate_sources(draft.source_ids, scope)
        item_type = KnowledgeItemType(draft.item_type)
        metadata = dict(draft.metadata)
        metadata.update(
            {
                "workspace_id": artifact.workspace_id,
                "source_ids": list(draft.source_ids),
                "source_quote": draft.source_quote,
                "ai_content": draft.ai_content or draft.summary,
                "provenance": "knowledge_curator",
            }
        )
        if draft.subtype:
            metadata["subtype"] = draft.subtype
        if draft.existing_item_id:
            if draft.expected_version != 1 or not draft.expected_content_hash:
                raise CuratorCommitConflictError(
                    "existing knowledge item requires expected_version=1 and a content hash"
                )
            if (
                scope.mode is ScopeMode.RESTRICTED
                and draft.existing_item_id not in scope.allowed_item_ids
            ):
                raise CuratorCommitError(
                    "target knowledge item is outside the authorized scope"
                )
            current = self._knowledge.get_item(draft.existing_item_id)
            if current is None:
                raise CuratorCommitConflictError(
                    "target knowledge item no longer exists"
                )
            if (
                draft.expected_content_hash
                and knowledge_item_content_hash(current) != draft.expected_content_hash
            ):
                raise CuratorCommitConflictError(
                    "knowledge item changed after the draft was prepared"
                )
            updated = self._knowledge.update_item(
                current.item_id,
                item_type=item_type,
                title=draft.title,
                summary=draft.summary,
                metadata={**current.metadata, **metadata},
            )
            assert updated is not None
            return updated.item_id
        if draft.expected_version != 0 or draft.expected_content_hash:
            raise CuratorCommitConflictError(
                "new knowledge item must use expected_version=0 without a content hash"
            )
        item_id = self._stable_id("ki", operation_id, f"item:{draft.draft_id}")
        existing = self._knowledge.get_item(item_id)
        if existing is not None:
            expected = {
                "item_type": item_type,
                "title": draft.title,
                "summary": draft.summary,
            }
            if any(getattr(existing, key) != value for key, value in expected.items()):
                raise CuratorCommitConflictError(
                    "stable item ID already contains different content"
                )
            return existing.item_id
        return self._knowledge.create_item(
            item_id=item_id,
            item_type=item_type,
            title=draft.title,
            summary=draft.summary,
            resource_document_id=(
                draft.source_ids[0]
                if draft.source_ids
                and draft.source_ids[0] in scope.allowed_document_ids
                else None
            ),
            metadata=metadata,
        ).item_id

    def apply(
        self,
        *,
        artifact_id: str,
        artifact_version: int,
        operation_id: str,
        scope: ScopeContext,
        selected_draft_ids: list[str] | None = None,
    ) -> CuratorCommitReceipt:
        operation = str(operation_id).strip()
        if not operation:
            raise CuratorCommitError("operation_id is required")
        artifact = self._artifacts.get(artifact_id, artifact_version)
        if not isinstance(artifact, KnowledgeDraftArtifact):
            raise CuratorCommitError(
                "knowledge draft artifact not found or has the wrong type"
            )
        self._validate_scope(artifact, scope)
        selected = {
            str(item).strip()
            for item in (selected_draft_ids or [])
            if str(item).strip()
        }
        all_ids = (
            {item.draft_id for item in artifact.notes}
            | {item.draft_id for item in artifact.items}
            | {item.proposal_id for item in artifact.relation_proposals}
        )
        if selected - all_ids:
            raise CuratorCommitError(
                f"unknown selected draft IDs: {sorted(selected - all_ids)}"
            )
        if not selected:
            selected = all_ids
        payload_hash = self._payload_hash(
            artifact=artifact, scope=scope, selected_draft_ids=selected
        )
        previous = self.get_receipt(operation)
        if previous is not None and previous.payload_hash != payload_hash:
            raise CuratorCommitConflictError(
                "operation_id was already used for different content or targets"
            )
        if previous is not None and previous.status == "completed":
            return previous.model_copy(update={"replayed": True})

        results_by_key = {
            item.target_key: item
            for item in (previous.results if previous is not None else [])
            if item.status == "committed"
        }
        receipt = CuratorCommitReceipt(
            operation_id=operation,
            payload_hash=payload_hash,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.version,
            workspace_id=artifact.workspace_id,
            status="in_progress",
            results=list(results_by_key.values()),
        )
        self._save_receipt(receipt)
        draft_to_item: dict[str, str] = {}

        for draft in artifact.notes:
            if draft.draft_id not in selected:
                continue
            key = f"note:{draft.draft_id}"
            if key in results_by_key:
                draft_to_item[draft.draft_id] = self._stable_id(
                    "ki", operation, f"note-item:{draft.draft_id}"
                )
                continue
            try:
                note_id, item_id = self._commit_note(
                    operation_id=operation, artifact=artifact, draft=draft, scope=scope
                )
                draft_to_item[draft.draft_id] = item_id
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="note",
                    status="committed",
                    object_id=note_id,
                )
            except Exception as exc:  # noqa: BLE001 - batch commits report per-target failures
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="note",
                    status="failed",
                    error_code=type(exc).__name__,
                    message=str(exc),
                )
            receipt = receipt.model_copy(
                update={"results": list(results_by_key.values())}
            )
            self._save_receipt(receipt)

        for draft in artifact.items:
            if draft.draft_id not in selected:
                continue
            key = f"item:{draft.draft_id}"
            if key in results_by_key:
                draft_to_item[draft.draft_id] = results_by_key[key].object_id
                continue
            try:
                item_id = self._commit_item(
                    operation_id=operation, artifact=artifact, draft=draft, scope=scope
                )
                draft_to_item[draft.draft_id] = item_id
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="item",
                    status="committed",
                    object_id=item_id,
                )
            except Exception as exc:  # noqa: BLE001 - batch commits report per-target failures
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="item",
                    status="failed",
                    error_code=type(exc).__name__,
                    message=str(exc),
                )
            receipt = receipt.model_copy(
                update={"results": list(results_by_key.values())}
            )
            self._save_receipt(receipt)

        for proposal in artifact.relation_proposals:
            if proposal.proposal_id not in selected:
                continue
            key = f"relation_proposal:{proposal.proposal_id}"
            if key in results_by_key:
                continue
            try:
                if proposal.relation_type not in AI_SUGGESTIBLE_RELATION_TYPES:
                    raise CuratorCommitError("relation type is not AI-suggestible")
                source_id = draft_to_item.get(
                    proposal.source_draft_or_item_id, proposal.source_draft_or_item_id
                )
                target_id = draft_to_item.get(
                    proposal.target_draft_or_item_id, proposal.target_draft_or_item_id
                )
                if source_id == target_id:
                    raise CuratorCommitError("relation endpoints must differ")
                for endpoint in (source_id, target_id):
                    if self._knowledge.get_item(endpoint) is None:
                        raise CuratorCommitError("relation endpoint no longer exists")
                    if scope.mode is ScopeMode.RESTRICTED and endpoint not in set(
                        scope.allowed_item_ids
                    ) | set(draft_to_item.values()):
                        raise CuratorCommitError(
                            "relation endpoint is outside the authorized scope"
                        )
                if proposal.relation_type == "supports" and not proposal.evidence_ids:
                    raise CuratorCommitError("supports relation requires evidence")
                available_evidence = {
                    item.evidence_id for item in artifact.evidence_refs
                }
                if set(proposal.evidence_ids) - available_evidence:
                    raise CuratorCommitError(
                        "relation evidence is no longer present in the artifact"
                    )
                suggestion_id = self._stable_id("krs", operation, key)
                existing = self._suggestions.get(suggestion_id)
                if existing is None:
                    focus_id = source_id
                    suggestion = KnowledgeRelationSuggestion(
                        suggestion_id=suggestion_id,
                        focus_item_id=focus_id,
                        source_item_id=source_id,
                        target_item_id=target_id,
                        relation_type=proposal.relation_type,
                        rationale=proposal.rationale,
                        confidence=proposal.confidence,
                        evidence_item_ids=list(proposal.evidence_ids),
                        metadata={
                            "workspace_id": artifact.workspace_id,
                            "artifact_id": artifact.artifact_id,
                            "proposal_id": proposal.proposal_id,
                            "provenance": "knowledge_curator",
                        },
                    )
                    existing = self._suggestions.save(suggestion)
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="relation_proposal",
                    status="committed",
                    object_id=existing.suggestion_id,
                )
            except Exception as exc:  # noqa: BLE001 - batch commits report per-target failures
                results_by_key[key] = CuratorCommitTargetResult(
                    target_key=key,
                    target_kind="relation_proposal",
                    status="failed",
                    error_code=type(exc).__name__,
                    message=str(exc),
                )
            receipt = receipt.model_copy(
                update={"results": list(results_by_key.values())}
            )
            self._save_receipt(receipt)

        results = list(results_by_key.values())
        failures = [item for item in results if item.status == "failed"]
        committed = [item for item in results if item.status == "committed"]
        status = "completed" if not failures else "partial" if committed else "failed"
        return self._save_receipt(
            receipt.model_copy(update={"status": status, "results": results})
        )


__all__ = [
    "CuratorCommitConflictError",
    "CuratorCommitError",
    "CuratorCommitService",
    "knowledge_item_content_hash",
    "research_note_content_hash",
]
