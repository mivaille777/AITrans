from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.services.reading_context_adapter import to_reading_context


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_document_ids(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        document_id = str(value or "").strip()
        if document_id and document_id not in seen:
            normalized.append(document_id)
            seen.add(document_id)
        if len(normalized) >= 100:
            break
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class CompanionHandoffState:
    revision: int
    handoff_id: str
    created_at: str
    source_text: str
    translated_text: str = ""
    source_language: str = "auto"
    target_language: str = "zh-CN"
    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    context_before: str = ""
    context_after: str = ""
    source_kind: str = "browser_selection"
    conversation_id: str = ""
    ai_content: str = ""
    ai_action: str = ""
    suggested_prompt: str = ""
    knowledge_enabled: bool = False
    knowledge_document_ids: tuple[str, ...] = ()


class CompanionHandoffService:
    """Thread-safe latest-context handoff between overlay and the main workspace.

    Stage 6D can recover missing prompt-safe metadata from the unified reading
    resolver when the handoff text still matches the current/cached selection.
    Explicit handoff fields always win.
    """

    def __init__(self, *, reading_resolver: Any | None = None) -> None:
        self._lock = RLock()
        self._revision = 0
        self._handoff: CompanionHandoffState | None = None
        self._reading_resolver = reading_resolver

    def snapshot(self) -> CompanionHandoffState | None:
        with self._lock:
            return self._handoff

    def _resolved_reading_fields(
        self,
        *,
        source_text: str,
        resource_url: str,
        resource_title: str,
        section_heading: str,
        context_before: str,
        context_after: str,
        source_kind: str,
    ) -> tuple[str, str, str, str, str, str]:
        resolver = self._reading_resolver
        resolve_for_text = getattr(resolver, "resolve_for_text", None)
        if not callable(resolve_for_text):
            return (
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
                resource_url,
                resource_title,
                section_heading,
                context_before,
                context_after,
                source_kind,
            )

        reading = to_reading_context(selection)
        resolved_kind = source_kind
        if reading.source_kind and (
            not str(source_kind or "").strip()
            or str(source_kind).strip() == "browser_selection"
        ):
            resolved_kind = reading.source_kind
        return (
            resource_url or reading.resource_url,
            resource_title or reading.resource_title,
            section_heading or reading.section_heading,
            context_before or reading.context_before,
            context_after or reading.context_after,
            resolved_kind,
        )

    def create(
        self,
        *,
        source_text: str,
        translated_text: str = "",
        source_language: str = "auto",
        target_language: str = "zh-CN",
        resource_url: str = "",
        resource_title: str = "",
        section_heading: str = "",
        context_before: str = "",
        context_after: str = "",
        source_kind: str = "browser_selection",
        conversation_id: str = "",
        ai_content: str = "",
        ai_action: str = "",
        suggested_prompt: str = "",
        knowledge_enabled: bool = False,
        knowledge_document_ids: list[str] | tuple[str, ...] = (),
    ) -> CompanionHandoffState:
        text = str(source_text).strip()
        if not text:
            raise ValueError("Companion handoff requires selected source text.")

        (
            resource_url,
            resource_title,
            section_heading,
            context_before,
            context_after,
            source_kind,
        ) = self._resolved_reading_fields(
            source_text=text,
            resource_url=resource_url,
            resource_title=resource_title,
            section_heading=section_heading,
            context_before=context_before,
            context_after=context_after,
            source_kind=source_kind,
        )
        document_ids = _normalized_document_ids(knowledge_document_ids)

        with self._lock:
            self._revision += 1
            self._handoff = CompanionHandoffState(
                revision=self._revision,
                handoff_id=uuid4().hex,
                created_at=_now_iso(),
                source_text=text,
                translated_text=str(translated_text or "").strip(),
                source_language=str(source_language or "auto").strip() or "auto",
                target_language=str(target_language or "zh-CN").strip() or "zh-CN",
                resource_url=str(resource_url or "").strip(),
                resource_title=str(resource_title or "").strip(),
                section_heading=str(section_heading or "").strip(),
                context_before=str(context_before or "").strip(),
                context_after=str(context_after or "").strip(),
                source_kind=str(source_kind or "browser_selection").strip()
                or "browser_selection",
                conversation_id=str(conversation_id or "").strip(),
                ai_content=str(ai_content or "").strip(),
                ai_action=str(ai_action or "").strip(),
                suggested_prompt=str(suggested_prompt or "").strip(),
                knowledge_enabled=bool(knowledge_enabled and document_ids),
                knowledge_document_ids=document_ids,
            )
            return self._handoff

    def clear(self, *, handoff_id: str = "") -> CompanionHandoffState | None:
        """Clear only the handoff the caller observed.

        A stale main-window dismissal must never erase a newer overlay handoff.
        """

        identifier = str(handoff_id or "").strip()
        with self._lock:
            current = self._handoff
            if current is None:
                return None
            if identifier and identifier != current.handoff_id:
                return current
            self._revision += 1
            self._handoff = None
            return None
