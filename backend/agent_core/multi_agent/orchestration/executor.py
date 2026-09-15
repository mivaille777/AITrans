from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List

from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector


class AgentExecutor:
    """Execute planned tasks through registered agents with context injection."""

    def __init__(
        self,
        registry=None,
        context_manager=None,
        knowledge_injector=None,
        memory_adapter=None,
        trace_collector: MultiAgentTraceCollector | None = None,
    ):
        self.registry = registry
        self.context_manager = context_manager
        self.knowledge_injector = knowledge_injector
        self.memory_adapter = memory_adapter
        self.trace_collector = trace_collector

    @staticmethod
    def _emit(
        collector: MultiAgentTraceCollector | None,
        event_type: str,
        *,
        actor: str,
        status: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        if collector is None:
            return
        collector.emit(
            event_type,
            actor=actor,
            status=status,
            payload=payload,
        )

    def execute(
        self,
        plan: List[Dict[str, Any]],
        context: Any = None,
        user_id: str | None = None,
        trace_collector: MultiAgentTraceCollector | None = None,
    ):
        results = []
        collector = trace_collector or self.trace_collector

        if context is not None:
            if self.memory_adapter is not None:
                loaded_memory = self.memory_adapter.load(user_id)
                context.memory.update(loaded_memory)
                self._emit(
                    collector,
                    "memory_loaded",
                    actor="shared_context",
                    status="complete",
                    payload={"memory_key_count": len(loaded_memory)},
                )

            if self.knowledge_injector is not None:
                self._emit(
                    collector,
                    "knowledge_retrieval_started",
                    actor="knowledge",
                    status="running",
                )
                started_at = perf_counter()
                try:
                    context = self.knowledge_injector.inject(
                        context.query,
                        context,
                    )
                except Exception as exc:
                    self._emit(
                        collector,
                        "knowledge_retrieval_failed",
                        actor="knowledge",
                        status="failed",
                        payload={"error_type": type(exc).__name__},
                    )
                    raise
                self._emit(
                    collector,
                    "knowledge_retrieved",
                    actor="knowledge",
                    status="complete",
                    payload={
                        "duration_ms": max(0, int((perf_counter() - started_at) * 1000)),
                        "citation_count": len(getattr(context, "citations", []) or []),
                        "context_chars": len(str(getattr(context, "knowledge_context", "") or "")),
                    },
                )

            self._emit(
                collector,
                "shared_context_ready",
                actor="shared_context",
                status="complete",
                payload={
                    "citation_count": len(getattr(context, "citations", []) or []),
                    "memory_key_count": len(getattr(context, "memory", {}) or {}),
                    "result_count": len(getattr(context, "intermediate_results", {}) or {}),
                },
            )

        for item in plan:
            agent_name = str(item.get("agent") or "").strip()
            task = item.get("task")

            if self.registry is None:
                self._emit(
                    collector,
                    "agent_skipped",
                    actor=agent_name or "unknown",
                    status="warning",
                    payload={"reason": "registry_unavailable"},
                )
                continue

            agent = self.registry.get(agent_name)
            if agent is None:
                self._emit(
                    collector,
                    "agent_skipped",
                    actor=agent_name or "unknown",
                    status="warning",
                    payload={"reason": "agent_not_registered"},
                )
                continue

            self._emit(
                collector,
                "agent_started",
                actor=agent_name,
                status="running",
            )
            started_at = perf_counter()
            try:
                result = agent.execute(task, context)
            except Exception as exc:
                self._emit(
                    collector,
                    "agent_failed",
                    actor=agent_name,
                    status="failed",
                    payload={"error_type": type(exc).__name__},
                )
                raise

            results.append(result)
            metadata = getattr(result, "metadata", {}) or {}
            self._emit(
                collector,
                "agent_completed",
                actor=agent_name,
                status="complete",
                payload={
                    "duration_ms": max(0, int((perf_counter() - started_at) * 1000)),
                    "role": str(metadata.get("role", "") or ""),
                },
            )

            if self.context_manager is not None and context is not None:
                self.context_manager.update_agent_result(
                    context,
                    agent_name,
                    result,
                )
                self._emit(
                    collector,
                    "shared_context_updated",
                    actor="shared_context",
                    status="complete",
                    payload={
                        "agent": agent_name,
                        "result_count": len(getattr(context, "intermediate_results", {}) or {}),
                    },
                )

            if self.memory_adapter is not None:
                self.memory_adapter.save(result, user_id)

        self._emit(
            collector,
            "workflow_completed",
            actor="supervisor",
            status="complete",
            payload={"completed_agent_count": len(results)},
        )
        return results
