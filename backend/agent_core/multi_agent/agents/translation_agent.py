from __future__ import annotations

from backend.agent_core.multi_agent.base_agent import BaseAgent, AgentResult


class TranslationAgent(BaseAgent):
    name = "translation"

    def execute(self, task: str, context=None) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            output=f"Translation task prepared: {task}",
            metadata={"role": "translation"},
        )


__all__ = ["TranslationAgent"]
