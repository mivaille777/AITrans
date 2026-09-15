from __future__ import annotations

from typing import Dict

from .base_agent import BaseAgent


class AgentRegistry:
    """Runtime registry for dynamically managed agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())


__all__ = ["AgentRegistry"]
