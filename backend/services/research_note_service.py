from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.ai.chat.models import ChatContext, ReadingContext
from app.research.notes import ResearchNote, ResearchNoteSaveResult, ResearchNoteStore
from backend.services.reading_context_adapter import to_reading_context
from backend.services.research_source_profile import (
    ResearchSourceProfile,
    ResearchSourceSummary,
    research_source_id,
    summarize_source,
)

_RESEARCH_SEARCH_SCAN_LIMIT = 100
_RESEARCH_SEARCH_DEFAULT_LIMIT = 8
_RESEARCH_SEARCH_MAX_LIMIT = 20
_SEARCH_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ResearchNoteSearchMatch:
    note: ResearchNote
    source_id: str
    score: float


def _search_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _query_tokens(query: str) -> tuple[str, ...]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _SEARCH_TOKEN_RE.findall(query.casefold()):
        normalized = token.strip("_-")
        if normalized and normalized not in seen:
            tokens.append(normalized)
            seen.add(normalized)
    return tuple(tokens)


def _field_score(*, value: object, query: str, tokens: tuple[str, ...], weight: float) -> float:
    text = _search_text(value)
    if not text:
        return 0.0
    score = 0.0
    if query and query in text:
        score += weight * 2.0
    if tokens:
        matched = sum(1 for token in tokens if token in text)
        score += weight * (matched / len(tokens))
    return score


def _note_search_score(note: ResearchNote, *, query: str, tokens: tuple[str, ...]) -> float:
    weighted_fields = (
        (note.resource_title, 6.0),
        (note.section_heading, 5.0),
        (note.user_note, 4.5),
        (note.ai_content, 3.5),
        (note.source_text, 3.0),
        (note.translated_text, 2.5),
        (note.context_before, 1.0),
        (note.context_after, 1.0),
    )
    return round(
        sum(
            _field_score(value=value, query=query, tokens=tokens, weight=weight)
            for value, weight in weighted_fields
        ),
        6,
    )


class ResearchNoteService:
    """Application boundary around the existing SQLite research-note store.

    When the supplied text still matches the unified reading resolver, missing
    source metadata is filled from that frozen selection. Stage 16 optionally
    associates newly saved notes/conversations with a Research Workspace without
    changing the underlying note schema.
    """

    def __init__(
        self,
        store: ResearchNoteStore | Any | None = None,
        *,
        reading_resolver: Any | None = None,
        workspace_service: Any | None = None,
    ) -> None:
        self._store = store or ResearchNoteStore()
        self._reading_resolver = reading_resolver
        self._workspace_service = workspace_service

    def _resolved_fields(
        self,
        *,
        source_text: str,
        resource_url: str,
        resource_title: str,
        section_heading: str,
        context_before: str,
        context_after: str,
        source_kind: str,
    ) -> tuple[str, str, str, str, str, str, str]:
        resolver = self._reading_resolver
        resolve_for_text = getattr(resolver, "resolve_for_text", None)
        if not callable(resolve_for_text):
            return (
                source_text,
                resource_url,
                resource_title,
                section_heading,
                context_before,
                context_after,
                source_kind,
            )

        try:
            selection = resolve_for_text(source_text)
        except Exception:
            selection = None
        if selection is None:
            return (
                source_text,
                resource_url,
                resource_title,
                section_heading,
                context_before,
                context_after,
                source_kind,
            )

        reading = to_reading_context(selection)
        resolved_source_kind = source_kind
        if reading.source_kind and (
            not str(source_kind or "").strip()
            or str(source_kind).strip() == "browser_selection"
        ):
            resolved_source_kind = reading.source_kind
        return (
            source_text or selection.text,
            resource_url or reading.resource_url,
            resource_title or reading.resource_title,
            section_heading or reading.section_heading,
            context_before or reading.context_before,
            context_after or reading.context_after,
            resolved_source_kind,
        )

    def save(
        self,
        *,
        source_text: str = "",
        translated_text: str = "",
        source_language: str = "auto",
        target_language: str = "zh-CN",
        resource_url: str = "",
        resource_title: str = "",
        section_heading: str = "",
        context_before: str = "",
        context_after: str = "",
        source_kind: str = "browser_selection",
        ai_content: str = "",
        ai_action: str = "",
        user_note: str = "",
        conversation_id: str = "",
        workspace_id: str = "",
    ) -> ResearchNoteSaveResult:
        _ = (source_language, target_language)
        (
            source_text,
            resource_url,
            resource_title,
            section_heading,
            context_before,
            context_after,
            source_kind,
        ) = self._resolved_fields(
            source_text=source_text,
            resource_url=resource_url,
            resource_title=resource_title,
            section_heading=section_heading,
            context_before=context_before,
            context_after=context_after,
            source_kind=source_kind,
        )
        if not source_text.strip():
            raise ValueError("Research note requires selected source text.")

        context = ChatContext(
            source_text=source_text,
            translated_text=translated_text,
            reading=ReadingContext(
                resource_url=resource_url,
                resource_title=resource_title,
                section_heading=section_heading,
                context_before=context_before,
                context_after=context_after,
                source_kind=source_kind,
            ),
        )
        result = self._store.save_context(
            context,
            ai_content=ai_content,
            ai_action=ai_action,
            user_note=user_note,
            conversation_id=conversation_id,
        )
        workspace = str(workspace_id or "").strip()
        service = self._workspace_service
        if workspace and service is not None:
            if not service.attach_note(workspace, result.note.note_id):
                raise ValueError("Research workspace not found.")
            conversation = str(conversation_id or "").strip()
            if conversation:
                service.attach_conversation(workspace, conversation)
        return result

    def list_recent(self, *, limit: int = 5) -> tuple[ResearchNote, ...]:
        return tuple(self._store.list_recent(limit=limit))

    def search(
        self,
        query: str,
        *,
        limit: int = _RESEARCH_SEARCH_DEFAULT_LIMIT,
        source_ids: tuple[str, ...] | list[str] = (),
        note_ids: tuple[str, ...] | list[str] = (),
    ) -> tuple[ResearchNoteSearchMatch, ...]:
        """Rank persisted research memory without invoking an LLM.

        ``source_ids`` remains available for the Stage 13 user-selected source
        scope. ``note_ids`` is a narrower runtime-only Stage 16 scope resolved
        from a Research Workspace and is never exposed to the planner.
        """

        normalized_query = _search_text(query)
        if not normalized_query:
            raise ValueError("Research-note search query must not be empty.")
        try:
            bounded_limit = max(1, min(_RESEARCH_SEARCH_MAX_LIMIT, int(limit)))
        except (TypeError, ValueError):
            bounded_limit = _RESEARCH_SEARCH_DEFAULT_LIMIT

        trusted_sources = {
            str(source_id or "").strip()
            for source_id in source_ids
            if str(source_id or "").strip()
        }
        trusted_notes = {
            str(note_id or "").strip()
            for note_id in note_ids
            if str(note_id or "").strip()
        }
        tokens = _query_tokens(normalized_query)
        matches: list[ResearchNoteSearchMatch] = []
        for note in self.list_recent(limit=_RESEARCH_SEARCH_SCAN_LIMIT):
            if trusted_notes and note.note_id not in trusted_notes:
                continue
            source_id = research_source_id(note)
            if trusted_sources and source_id not in trusted_sources:
                continue
            score = _note_search_score(note, query=normalized_query, tokens=tokens)
            if score <= 0:
                continue
            matches.append(
                ResearchNoteSearchMatch(
                    note=note,
                    source_id=source_id,
                    score=score,
                )
            )

        matches.sort(
            key=lambda item: (item.score, item.note.updated_at, item.note.note_id),
            reverse=True,
        )
        return tuple(matches[:bounded_limit])

    def get(self, note_id: str) -> ResearchNote | None:
        getter = getattr(self._store, "get", None)
        if not callable(getter):
            return None
        return getter(note_id)

    def update_user_note(self, note_id: str, user_note: str) -> ResearchNote | None:
        updater = getattr(self._store, "update_user_note", None)
        if not callable(updater):
            raise RuntimeError("Research note editing is unavailable.")
        return updater(note_id, user_note)

    def delete(self, note_id: str) -> bool:
        return bool(self._store.delete(note_id))

    def count(self) -> int:
        return int(self._store.count())

    def _group_source_notes(self, *, limit: int = 100) -> dict[str, tuple[ResearchNote, ...]]:
        grouped: dict[str, list[ResearchNote]] = {}
        for note in self.list_recent(limit=limit):
            grouped.setdefault(research_source_id(note), []).append(note)
        return {source_id: tuple(notes) for source_id, notes in grouped.items()}

    def list_sources(self, *, limit: int = 100) -> tuple[ResearchSourceSummary, ...]:
        profiles = [
            summarize_source(notes)
            for notes in self._group_source_notes(limit=limit).values()
        ]
        profiles.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(
            ResearchSourceSummary(
                source_id=item.source_id,
                display_title=item.display_title,
                resource_url=item.resource_url,
                resource_locator=item.resource_locator,
                source_kind=item.source_kind,
                source_family=item.source_family,
                identity_quality=item.identity_quality,
                note_count=item.note_count,
                section_count=item.section_count,
                linked_conversation_count=item.linked_conversation_count,
                annotation_count=item.annotation_count,
                ai_evidence_count=item.ai_evidence_count,
                updated_at=item.updated_at,
            )
            for item in profiles
        )

    def get_source(self, source_id: str, *, limit: int = 100) -> ResearchSourceProfile | None:
        candidate = str(source_id or "").strip()
        if not candidate:
            return None
        notes = self._group_source_notes(limit=limit).get(candidate)
        if not notes:
            return None
        return summarize_source(notes)


__all__ = [
    "ResearchNoteSearchMatch",
    "ResearchNoteService",
    "ResearchSourceProfile",
    "ResearchSourceSummary",
    "research_source_id",
]
