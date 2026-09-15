from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeRouteDecision:
    """Decision returned by the lightweight supervisor layer."""

    need_knowledge: bool
    reason: str
    tool_name: str = ""


class SupervisorKnowledgeRouter:
    """Route agent requests that benefit from grounded knowledge retrieval."""

    _knowledge_keywords = {
        "explain", "why", "according", "paper", "document", "reference",
        "knowledge", "context", "compare", "summarize", "总结", "解释",
        "论文", "资料",
    }

    def decide(self, state: Any) -> KnowledgeRouteDecision:
        text = str(getattr(state, "user_input", "") or "").lower()
        matched = [item for item in self._knowledge_keywords if item in text]
        if matched:
            return KnowledgeRouteDecision(
                need_knowledge=True,
                reason=f"matched knowledge intent: {', '.join(sorted(matched))}",
                tool_name="search_knowledge_base",
            )
        return KnowledgeRouteDecision(
            need_knowledge=False,
            reason="no grounded knowledge intent detected",
        )

    def build_plan(self, state: Any) -> dict[str, Any]:
        """Create an execution hint consumed by Agent workflow adapters."""
        decision = self.decide(state)
        return {
            "decision": decision,
            "steps": [
                {
                    "action": "retrieve_knowledge",
                    "tool": decision.tool_name,
                }
            ] if decision.need_knowledge else [],
        }


__all__ = ["KnowledgeRouteDecision", "SupervisorKnowledgeRouter"]
