from __future__ import annotations

from typing import Any


class AgentKnowledgeTraceProjector:
    """Project knowledge retrieval lifecycle data into UI-friendly trace data."""

    def build(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        knowledge_events = [
            event for event in events
            if str(event.get("event_type", "")).startswith("knowledge_")
        ]

        return {
            "knowledge_trace": knowledge_events,
            "retrieved_sources": [
                item
                for event in knowledge_events
                for item in event.get("payload", {}).get("citations", [])
            ],
        }
