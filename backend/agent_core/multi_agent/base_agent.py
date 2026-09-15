from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    agent_name: str
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """Common interface for specialized AITrans agents."""

    name = "base"

    def execute(self, task: str, context: dict[str, Any] | None = None) -> AgentResult:
        raise NotImplementedError


__all__ = ["BaseAgent", "AgentResult"]
