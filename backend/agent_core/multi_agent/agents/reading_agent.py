from __future__ import annotations

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class ReadingAgent(BaseAgent):
    name = "reading"

    def execute(self, task: str, context=None) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            output=f"Reading analysis prepared: {task}",
            metadata={"role": "document_analysis"},
        )


__all__ = ["ReadingAgent"]
