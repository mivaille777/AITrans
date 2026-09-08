from typing import Any, Dict, List


class AgentExecutor:
    """Execute planned tasks through registered agents."""

    def __init__(self, registry=None, context_manager=None):
        self.registry = registry
        self.context_manager = context_manager

    def execute(self, plan: List[Dict[str, Any]], context: Any = None):
        results = []

        for item in plan:
            agent_name = item.get("agent")
            task = item.get("task")

            if self.registry is None:
                continue

            agent = self.registry.get(agent_name)
            if agent is None:
                continue

            result = agent.execute(task, context)
            results.append(result)

            if self.context_manager is not None:
                self.context_manager.update_agent_result(
                    agent_name,
                    result,
                )

        return results
