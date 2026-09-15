from __future__ import annotations

from typing import Any

from .agent_registry import AgentRegistry


class SupervisorOrchestrator:
    """Coordinate task assignment among registered agents."""

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def plan(self, task: str) -> dict[str, Any]:
        lowered = task.lower()
        steps = []

        if any(k in lowered for k in ["paper", "论文", "research", "研究"]):
            steps.append({"agent": "research", "task": task})

        if any(k in lowered for k in ["read", "阅读", "summarize", "总结"]):
            steps.append({"agent": "reading", "task": task})

        if any(k in lowered for k in ["translate", "翻译"]):
            steps.append({"agent": "translation", "task": task})

        if not steps:
            steps.append({"agent": "general", "task": task})

        return {"tasks": steps}

    def execute(self, task: str, context: dict[str, Any] | None = None):
        plan = self.plan(task)
        results = []
        for item in plan["tasks"]:
            agent = self.registry.get(item["agent"])
            if agent:
                results.append(agent.execute(item["task"], context))
        return {"plan": plan, "results": results}


__all__ = ["SupervisorOrchestrator"]
