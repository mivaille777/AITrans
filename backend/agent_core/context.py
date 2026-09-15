from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.agent_core.state import AgentState
from backend.services.reading_context_adapter import to_reading_context
from backend.services.reading_selection_resolver import ReadingSelectionResolver

_EXPLICIT_READING_CONTEXT_FIELDS = (
    "resource_url",
    "resource_title",
    "section_heading",
    "context_before",
    "context_after",
)


class ReadingContextProvider:
    """Enrich AgentState with the existing source-neutral reading pipeline.

    Explicit API context always wins. Native/browser selection resolution is a
    fallback only for requests whose explicit ``context_mode`` is ``reading``.
    General, Knowledge, Research and Translation requests must never inherit a
    short-lived cached reading selection merely because the user previously
    selected text in another surface.
    """

    def __init__(self, resolver: ReadingSelectionResolver | Any | None = None) -> None:
        self._resolver = resolver or ReadingSelectionResolver()

    @staticmethod
    def _has_explicit_context(context: dict[str, Any]) -> bool:
        return any(
            str(context.get(field, "") or "").strip()
            for field in _EXPLICIT_READING_CONTEXT_FIELDS
        )

    def __call__(self, state: AgentState) -> dict[str, Any]:
        context = dict(state.browser_context)
        context["source_text"] = state.selected_text
        mode = str(context.get("context_mode", "reading") or "reading").strip().lower()

        # Non-reading modes may still carry explicit source text for a bounded
        # tool (for example translation), but they must not ask the ambient
        # ReadingSelectionResolver to fill context from its cache.
        if mode != "reading":
            return context

        if self._has_explicit_context(context):
            return context

        selection = self._resolver.resolve_for_text(state.selected_text)
        if selection is None:
            return context

        if not state.selected_text.strip():
            state.selected_text = selection.text
        reading = to_reading_context(selection)
        context.update(asdict(reading))
        context["source_text"] = state.selected_text
        return context


__all__ = ["ReadingContextProvider"]
