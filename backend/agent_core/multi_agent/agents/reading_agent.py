from __future__ import annotations

from typing import Any

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class ReadingAgent(BaseAgent):
    """Prepare a bounded reading dossier from the active document context."""

    name = "reading"

    @staticmethod
    def _runtime(context: Any) -> dict[str, Any]:
        value = getattr(context, "runtime", {}) if context is not None else {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _research_findings(context: Any) -> list[dict[str, Any]]:
        if context is None:
            return []
        result = getattr(context, "intermediate_results", {}).get("research")
        output = getattr(result, "output", None)
        if not isinstance(output, dict):
            return []
        matches = output.get("matches", [])
        return [dict(item) for item in matches[:3] if isinstance(item, dict)]

    def execute(self, task: str, context=None) -> AgentResult:
        runtime = self._runtime(context)
        source_text = str(runtime.get("source_text", "") or "").strip()
        knowledge = str(getattr(context, "knowledge_context", "") or "").strip()
        research_findings = self._research_findings(context)

        primary = source_text or knowledge
        lines = [line.strip() for line in primary.splitlines() if line.strip()]
        dossier = {
            "task": str(task or "").strip(),
            "resource_title": str(runtime.get("resource_title", "") or ""),
            "section_heading": str(runtime.get("section_heading", "") or ""),
            "source_excerpt": primary[:1800],
            "source_chars": len(source_text),
            "knowledge_excerpt": knowledge[:1200],
            "research_findings": research_findings,
            "opening_points": lines[:5],
        }
        return AgentResult(
            agent_name=self.name,
            output=dossier,
            metadata={
                "role": "document_analysis",
                "source_chars": len(source_text),
                "knowledge_chars": len(knowledge),
                "research_context_used": bool(research_findings),
                "degraded": not bool(primary),
            },
        )


__all__ = ["ReadingAgent"]
