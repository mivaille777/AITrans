from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentKnowledgeContext:
    """Grounded knowledge payload carried between retrieval and response layers."""

    query: str = ""
    context_text: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved_nodes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not bool(self.context_text.strip() or self.evidence)

    def to_prompt_context(self) -> str:
        if self.is_empty():
            return ""
        lines = ["Grounded knowledge context:"]
        if self.context_text:
            lines.append(self.context_text)
        for item in self.evidence:
            title = str(item.get("title", "") or item.get("id", ""))
            text = str(item.get("text", "") or "")
            lines.append(f"- {title}: {text}")
        return "\n".join(lines)


__all__ = ["AgentKnowledgeContext"]
