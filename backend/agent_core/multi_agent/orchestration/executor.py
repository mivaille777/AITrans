from typing import Any, Dict, List


class AgentExecutor:
    """Execute planned tasks through registered agents with context injection."""

    def __init__(
        self,
        registry=None,
        context_manager=None,
        knowledge_injector=None,
        memory_adapter=None,
    ):
        self.registry = registry
        self.context_manager = context_manager
        self.knowledge_injector = knowledge_injector
        self.memory_adapter = memory_adapter

    def execute(
        self,
        plan: List[Dict[str, Any]],
        context: Any = None,
        user_id: str | None = None,
    ):
        results = []

        if context is not None:
            if self.memory_adapter is not None:
                context.memory.update(
                    self.memory_adapter.load(user_id)
                )

            if self.knowledge_injector is not None:
                context = self.knowledge_injector.inject(
                    context.query,
                    context,
                )

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

            if self.context_manager is not None and context is not None:
                self.context_manager.update_agent_result(
                    context,
                    agent_name,
                    result,
                )

            if self.memory_adapter is not None:
                self.memory_adapter.save(result, user_id)

        return results
