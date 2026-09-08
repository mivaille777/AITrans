from __future__ import annotations

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class ResearchAgent(BaseAgent):
    name = "research"

    def execute(self, task: str, context=None) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            output=f"Research task prepared: {task}",
            metadata={"role": "literature_research"},
        )


__all__ = ["ResearchAgent"]
