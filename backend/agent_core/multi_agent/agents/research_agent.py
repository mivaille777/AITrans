from __future__ import annotations

from typing import Any

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class ResearchAgent(BaseAgent):
    """Read-only specialist backed by the persisted Research Memory service."""

    name = "research"

    def __init__(self, research_service: Any | None = None, *, limit: int = 5) -> None:
        self.research_service = research_service
        self.limit = max(1, min(10, int(limit)))

    @staticmethod
    def _runtime(context: Any) -> dict[str, Any]:
        value = getattr(context, "runtime", {}) if context is not None else {}
        return value if isinstance(value, dict) else {}

    def execute(self, task: str, context=None) -> AgentResult:
        query = str(task or "").strip()
        runtime = self._runtime(context)
        source_ids = runtime.get("research_source_ids", ())
        if not isinstance(source_ids, (list, tuple)):
            source_ids = ()

        matches: list[dict[str, Any]] = []
        degraded = self.research_service is None
        if self.research_service is not None and query:
            try:
                found = self.research_service.search(
                    query,
                    limit=self.limit,
                    source_ids=[str(item) for item in source_ids if str(item).strip()],
                )
                for match in found:
                    note = match.note
                    matches.append(
                        {
                            "note_id": str(note.note_id),
                            "source_id": str(match.source_id),
                            "title": str(note.display_title or note.resource_title or "Research note"),
                            "section": str(note.section_heading or ""),
                            "excerpt": str(note.source_text or note.ai_content or note.user_note or "")[:900],
                            "score": float(match.score),
                        }
                    )
            except Exception:
                degraded = True

        knowledge_excerpt = str(getattr(context, "knowledge_context", "") or "")[:1200]
        return AgentResult(
            agent_name=self.name,
            output={
                "query": query,
                "matches": matches,
                "knowledge_excerpt": knowledge_excerpt,
            },
            metadata={
                "role": "literature_research",
                "source": "research_memory",
                "match_count": len(matches),
                "degraded": degraded,
            },
        )


__all__ = ["ResearchAgent"]
