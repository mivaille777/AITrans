from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agent_core.multi_agent.agent_registry import AgentRegistry
from backend.agent_core.multi_agent.agents import ReadingAgent, ResearchAgent, TranslationAgent
from backend.agent_core.multi_agent.base_agent import AgentResult
from backend.agent_core.multi_agent.context import (
    AgentMemoryAdapter,
    KnowledgeInjector,
    SharedAgentContext,
    SharedContextManager,
)
from backend.agent_core.multi_agent.orchestration import AgentExecutor, AgentPlanner
from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector, MultiAgentTraceEvent
from backend.services.agent_knowledge_runtime import AgentKnowledgeRuntime


@dataclass(frozen=True, slots=True)
class MultiAgentWorkspaceRun:
    run_id: str
    trace_id: str
    plan: tuple[dict[str, Any], ...]
    results: tuple[AgentResult, ...]
    context: SharedAgentContext
    events: tuple[MultiAgentTraceEvent, ...]
    total_duration_ms: int


class MultiAgentWorkspaceService:
    """Compose Stage 5 runtime pieces into one traceable workspace execution."""

    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        planner: AgentPlanner | None = None,
        context_manager: SharedContextManager | None = None,
        knowledge_injector: KnowledgeInjector | None = None,
        memory_adapter: AgentMemoryAdapter | None = None,
        research_service: Any | None = None,
        translation_service: Any | None = None,
    ) -> None:
        self.registry = registry or self._default_registry(
            research_service=research_service,
            translation_service=translation_service,
        )
        self.planner = planner or AgentPlanner()
        self.context_manager = context_manager or SharedContextManager()
        self.knowledge_injector = knowledge_injector or KnowledgeInjector(AgentKnowledgeRuntime())
        self.memory_adapter = memory_adapter or AgentMemoryAdapter()

    @staticmethod
    def _default_registry(
        *,
        research_service: Any | None = None,
        translation_service: Any | None = None,
    ) -> AgentRegistry:
        registry = AgentRegistry()
        registry.register(ResearchAgent(research_service))
        registry.register(ReadingAgent())
        registry.register(TranslationAgent(translation_service))
        return registry

    def run(
        self,
        task: str,
        *,
        user_id: str | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> MultiAgentWorkspaceRun:
        normalized_task = str(task or "").strip()
        if not normalized_task:
            raise ValueError("Multi-agent task must not be empty.")

        collector = MultiAgentTraceCollector(run_id=run_id, trace_id=trace_id)
        collector.emit(
            "supervisor_started",
            actor="supervisor",
            status="running",
            payload={"available_agents": self.registry.list_agents()},
        )

        context = self.context_manager.create(normalized_task)
        context.runtime.update(dict(runtime_context or {}))
        plan = self.planner.create_plan(normalized_task, context)
        collector.emit(
            "supervisor_planned",
            actor="supervisor",
            status="complete",
            payload={
                "task_count": len(plan),
                "agents": [str(item.get("agent") or "") for item in plan],
            },
        )

        executor = AgentExecutor(
            registry=self.registry,
            context_manager=self.context_manager,
            knowledge_injector=self.knowledge_injector,
            memory_adapter=self.memory_adapter,
        )
        results = executor.execute(
            plan,
            context,
            user_id=user_id,
            trace_collector=collector,
        )

        return MultiAgentWorkspaceRun(
            run_id=collector.run_id,
            trace_id=collector.trace_id,
            plan=tuple(dict(item) for item in plan),
            results=tuple(results),
            context=context,
            events=collector.events,
            total_duration_ms=collector.total_duration_ms,
        )


__all__ = ["MultiAgentWorkspaceRun", "MultiAgentWorkspaceService"]
