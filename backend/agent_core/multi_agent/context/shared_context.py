from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SharedAgentContext:
    """Shared workspace passed between specialized agents."""

    query: str = ""
    knowledge_context: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)

    def add_result(self, agent_name: str, result: Any) -> None:
        self.intermediate_results[agent_name] = result

    def add_citation(self, citation: dict[str, Any]) -> None:
        self.citations.append(citation)


__all__ = ["SharedAgentContext"]
