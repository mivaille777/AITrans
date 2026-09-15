from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from app.research.memory import (
    ResearchMemoryExtractionDraft,
    ResearchMemorySnapshot,
    ResearchMemoryStore,
)
from app.research.memory_reliability import ResearchMemoryReliabilityStore
from app.research.notes import ResearchNote
from backend.models.research_memory import ResearchMemorySearchResult
from backend.models.research_memory_reliability import (
    ResearchMemoryConflictGroup,
    ResearchMemoryReliabilitySummary,
    ResearchMemoryReliableSearchResult,
    ResearchMemorySourceStatus,
)
from backend.services.research_memory_reliability_service import (
    ResearchMemoryReliabilityService,
)

_SEARCH_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_DEFAULT_SEARCH_LIMIT = 12
_MAX_SEARCH_LIMIT = 50


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _tokens(value: str) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for token in _SEARCH_TOKEN_RE.findall(value.casefold()):
        item = token.strip("_-")
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _score(value: object, *, query: str, tokens: tuple[str, ...], weight: float) -> float:
    text = _normalized(value)
    if not text:
        return 0.0
    score = 0.0
    if query in text:
        score += weight * 2.0
    if tokens:
        matched = sum(1 for token in tokens if token in text)
        score += weight * (matched / len(tokens))
    return score


def _default_reliability_store(memory_store: Any) -> ResearchMemoryReliabilityStore:
    storage_path = getattr(memory_store, "storage_path", None)
    if storage_path is None:
        return ResearchMemoryReliabilityStore()
    path = Path(storage_path)
    return ResearchMemoryReliabilityStore(
        storage_path=path.with_name(f"{path.stem}_reliability.sqlite3")
    )


class ResearchMemoryService:
    """Workspace-scoped application boundary for Stage 17 structured memory."""

    def __init__(
        self,
        store: ResearchMemoryStore | Any | None = None,
        *,
        research_note_service: Any,
        workspace_service: Any,
        extraction_service: Any,
        reliability_store: ResearchMemoryReliabilityStore | Any | None = None,
        reliability_service: ResearchMemoryReliabilityService | Any | None = None,
    ) -> None:
        self._store = store or ResearchMemoryStore()
        self._research_notes = research_note_service
        self._workspaces = workspace_service
        self._extractor = extraction_service
        self._reliability = reliability_service or ResearchMemoryReliabilityService(
            memory_store=self._store,
            research_note_service=self._research_notes,
            revision_store=reliability_store or _default_reliability_store(self._store),
            workspace_service=self._workspaces,
        )

    def _workspace_note(self, workspace_id: str, note_id: str) -> ResearchNote:
        workspace = str(workspace_id or "").strip()
        note_identifier = str(note_id or "").strip()
        if not workspace or not note_identifier:
            raise ValueError("Structured research memory requires workspace_id and note_id.")
        profile = self._workspaces.get(workspace)
        if profile is None:
            raise ValueError("Research workspace not found.")
        if note_identifier not in set(profile.note_ids):
            raise ValueError("Research note is not attached to this workspace.")
        note = self._research_notes.get(note_identifier)
        if note is None:
            raise ValueError("Research note not found.")
        return note

    def _record_source_revision(self, *, workspace_id: str, note: ResearchNote) -> None:
        try:
            self._reliability.record_source_revision(
                workspace_id=workspace_id,
                note_id=note.note_id,
                source_fingerprint=str(getattr(note, "fingerprint", "") or ""),
            )
        except RuntimeError:
            return

    def persist_extraction(
        self,
        *,
        workspace_id: str,
        note_id: str,
        extraction: ResearchMemoryExtractionDraft,
    ):
        note = self._workspace_note(workspace_id, note_id)
        record = self._store.replace_note_memory(
            workspace_id=workspace_id,
            note_id=note_id,
            source_text=note.source_text,
            extraction=extraction,
        )
        self._record_source_revision(workspace_id=workspace_id, note=note)
        return record

    def extract_note(self, *, workspace_id: str, note_id: str):
        note = self._workspace_note(workspace_id, note_id)
        extraction = self._extractor.extract(note)
        record = self._store.replace_note_memory(
            workspace_id=workspace_id,
            note_id=note_id,
            source_text=note.source_text,
            extraction=extraction,
        )
        self._record_source_revision(workspace_id=workspace_id, note=note)
        return record

    def delete_note_memory(self, *, workspace_id: str, note_id: str) -> bool:
        self._workspace_note(workspace_id, note_id)
        deleted = bool(
            self._store.delete_note_memory(
                workspace_id=workspace_id,
                note_id=note_id,
            )
        )
        if deleted:
            self._reliability.delete_source_revision(
                workspace_id=workspace_id,
                note_id=note_id,
            )
        return deleted

    def snapshot(self, *, workspace_id: str, limit: int = 100) -> ResearchMemorySnapshot:
        workspace = str(workspace_id or "").strip()
        if not workspace or self._workspaces.get(workspace) is None:
            raise ValueError("Research workspace not found.")
        return self._store.snapshot(workspace_id=workspace, limit=limit)

    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> tuple[ResearchMemorySearchResult, ...]:
        normalized_query = _normalized(query)
        if not normalized_query:
            raise ValueError("Structured research-memory search query must not be empty.")
        try:
            bounded_limit = max(1, min(_MAX_SEARCH_LIMIT, int(limit)))
        except (TypeError, ValueError):
            bounded_limit = _DEFAULT_SEARCH_LIMIT

        snapshot = self.snapshot(workspace_id=workspace_id, limit=500)
        query_tokens = _tokens(normalized_query)
        results: list[ResearchMemorySearchResult] = []

        for claim in snapshot.claims:
            score = _score(
                claim.text,
                query=normalized_query,
                tokens=query_tokens,
                weight=6.0,
            ) + _score(
                claim.claim_type,
                query=normalized_query,
                tokens=query_tokens,
                weight=1.5,
            )
            if score > 0:
                results.append(
                    ResearchMemorySearchResult(
                        kind="claim",
                        item_id=claim.claim_id,
                        note_id=claim.note_id,
                        title=claim.claim_type,
                        text=claim.text,
                        score=round(score, 6),
                        claim_id=claim.claim_id,
                    )
                )

        for evidence in snapshot.evidence:
            score = _score(
                evidence.excerpt,
                query=normalized_query,
                tokens=query_tokens,
                weight=5.0,
            )
            if score > 0:
                results.append(
                    ResearchMemorySearchResult(
                        kind="evidence",
                        item_id=evidence.evidence_id,
                        note_id=evidence.note_id,
                        title="source evidence",
                        text=evidence.excerpt,
                        score=round(score, 6),
                        claim_id=evidence.claim_id,
                    )
                )

        for entity in snapshot.entities:
            alias_text = " ".join(entity.aliases)
            score = _score(
                entity.canonical_name,
                query=normalized_query,
                tokens=query_tokens,
                weight=6.5,
            ) + _score(
                alias_text,
                query=normalized_query,
                tokens=query_tokens,
                weight=3.5,
            ) + _score(
                entity.description,
                query=normalized_query,
                tokens=query_tokens,
                weight=2.5,
            )
            if score > 0:
                results.append(
                    ResearchMemorySearchResult(
                        kind="entity",
                        item_id=entity.entity_id,
                        title=f"{entity.entity_type}: {entity.canonical_name}",
                        text=entity.description or entity.canonical_name,
                        score=round(score, 6),
                        entity_id=entity.entity_id,
                    )
                )

        entity_by_id = {item.entity_id: item for item in snapshot.entities}
        for relation in snapshot.relations:
            subject = entity_by_id.get(relation.source_entity_id)
            target = entity_by_id.get(relation.target_entity_id)
            subject_name = subject.canonical_name if subject else relation.source_entity_id
            target_name = target.canonical_name if target else relation.target_entity_id
            text = f"{subject_name} {relation.predicate} {target_name}"
            score = _score(
                text,
                query=normalized_query,
                tokens=query_tokens,
                weight=5.5,
            )
            if score > 0:
                results.append(
                    ResearchMemorySearchResult(
                        kind="relation",
                        item_id=relation.relation_id,
                        note_id=relation.note_id,
                        title=relation.predicate,
                        text=text,
                        score=round(score, 6),
                        claim_id=relation.claim_id,
                    )
                )

        results.sort(
            key=lambda item: (item.score, item.kind, item.item_id),
            reverse=True,
        )
        return tuple(results[:bounded_limit])

    def search_reliable(
        self,
        *,
        workspace_id: str,
        query: str,
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> tuple[ResearchMemoryReliableSearchResult, ...]:
        results = self.search(workspace_id=workspace_id, query=query, limit=limit)
        snapshot = self.snapshot(workspace_id=workspace_id, limit=500)
        return self._reliability.enrich_results(
            workspace_id=workspace_id,
            results=results,
            snapshot=snapshot,
        )

    def source_status(
        self,
        *,
        workspace_id: str,
        note_id: str,
    ) -> ResearchMemorySourceStatus:
        return self._reliability.source_status(
            workspace_id=workspace_id,
            note_id=note_id,
        )

    def conflict_groups(
        self,
        *,
        workspace_id: str,
    ) -> tuple[ResearchMemoryConflictGroup, ...]:
        snapshot = self.snapshot(workspace_id=workspace_id, limit=500)
        return self._reliability.conflict_groups(
            workspace_id=workspace_id,
            snapshot=snapshot,
        )

    def reliability_summary(
        self,
        results: tuple[ResearchMemoryReliableSearchResult, ...],
    ) -> ResearchMemoryReliabilitySummary:
        return self._reliability.summarize(results)

    def close(self) -> None:
        close = getattr(self._extractor, "close", None)
        if callable(close):
            close()


__all__ = ["ResearchMemoryService"]
