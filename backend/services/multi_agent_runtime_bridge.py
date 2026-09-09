from __future__ import annotations

from typing import Any, Callable

from backend.agent_core.events import AgentEventType
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import AgentState
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService

CoreEventSink = Callable[[AgentEventType, dict[str, Any]], None]
_MAX_COLLAB_CONTEXT_CHARS = 6000

_EVENT_MAP: dict[str, AgentEventType] = {
    "supervisor_started": AgentEventType.MULTI_AGENT_STARTED,
    "supervisor_planned": AgentEventType.MULTI_AGENT_PLAN_READY,
    "knowledge_retrieval_started": AgentEventType.MULTI_AGENT_KNOWLEDGE_STARTED,
    "knowledge_retrieved": AgentEventType.MULTI_AGENT_KNOWLEDGE_READY,
    "shared_context_ready": AgentEventType.MULTI_AGENT_CONTEXT_READY,
    "shared_context_updated": AgentEventType.MULTI_AGENT_CONTEXT_READY,
    "agent_started": AgentEventType.MULTI_AGENT_SPECIALIST_STARTED,
    "agent_completed": AgentEventType.MULTI_AGENT_SPECIALIST_COMPLETED,
    "agent_failed": AgentEventType.MULTI_AGENT_SPECIALIST_FAILED,
    "agent_skipped": AgentEventType.MULTI_AGENT_SPECIALIST_SKIPPED,
    "workflow_completed": AgentEventType.MULTI_AGENT_COMPLETED,
}


class MultiAgentRuntimeBridge:
    """Pre-workflow collaboration bridge for the canonical AgentRuntime.

    The Stage 5 specialist layer contributes task decomposition and grounded
    shared context, while the mature ReadingAgentGraph remains authoritative for
    tool execution, confirmation, ReAct, synthesis, grounding, and the final
    response. This prevents a second independent Agent runtime from becoming a
    competing execution path.

    Collaboration is advisory and best-effort. If this layer is unavailable,
    the canonical Agent workflow continues unchanged rather than failing the
    user's request.
    """

    def __init__(self, service: MultiAgentWorkspaceService | None = None) -> None:
        self.service = service or MultiAgentWorkspaceService()

    def _plan(self, state: AgentState) -> list[dict[str, Any]]:
        return self.service.planner.create_plan(state.user_input, None)

    def should_run(self, state: AgentState) -> bool:
        mode = str(state.browser_context.get("multi_agent_mode", "auto") or "auto").strip().lower()
        if mode == "off":
            return False
        if mode == "force":
            return True
        plan = self._plan(state)
        agents = {
            str(item.get("agent", "") or "").strip()
            for item in plan
            if str(item.get("agent", "") or "").strip()
        }
        return len(agents) >= 2

    @staticmethod
    def _forward_events(run: Any, emit: CoreEventSink) -> None:
        for event in run.events:
            core_type = _EVENT_MAP.get(event.event_type)
            if core_type is None:
                continue
            payload = dict(event.payload or {})
            payload.update(
                {
                    "actor": event.actor,
                    "status": event.status,
                    "multi_agent_event_type": event.event_type,
                }
            )
            emit(core_type, payload)

    @staticmethod
    def _context_payload(run: Any) -> dict[str, Any]:
        context = run.context
        plan = [
            {
                "agent": str(item.get("agent", "") or ""),
                "task": str(item.get("task", "") or ""),
            }
            for item in run.plan
        ]
        return {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "plan": plan,
            "agents": [item["agent"] for item in plan if item["agent"]],
            "knowledge_context": str(context.knowledge_context or ""),
            "citations": [dict(item) for item in context.citations[:20]],
            "citation_count": len(context.citations),
            "knowledge_context_chars": len(str(context.knowledge_context or "")),
            "specialist_result_count": len(run.results),
            "total_duration_ms": run.total_duration_ms,
        }

    @staticmethod
    def _advisory_prompt_context(payload: dict[str, Any]) -> str:
        knowledge = str(payload.get("knowledge_context", "") or "").strip()
        agents = [str(item) for item in payload.get("agents", []) if str(item).strip()]
        if not knowledge and not agents:
            return ""
        lines = [
            "[Multi-Agent collaboration context]",
            "Treat this as advisory retrieved context; preserve normal grounding and safety checks.",
        ]
        if agents:
            lines.append(f"Selected specialist roles: {', '.join(agents)}")
        if knowledge:
            lines.append("Retrieved knowledge:")
            lines.append(knowledge)
        return "\n".join(lines)[:_MAX_COLLAB_CONTEXT_CHARS]

    def run_with_events(
        self,
        state: AgentState,
        emit: CoreEventSink,
        *,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        if not self.should_run(state):
            return state

        if control is not None:
            control.checkpoint("multi_agent_collaboration")

        try:
            run = self.service.run(
                state.user_input,
                user_id=state.session_id,
                run_id=state.run_id,
                trace_id=state.trace_id,
            )
        except Exception as exc:
            emit(
                AgentEventType.MULTI_AGENT_COMPLETED,
                {
                    "actor": "supervisor",
                    "status": "warning",
                    "multi_agent_event_type": "workflow_fallback",
                    "fallback_reason": "collaboration_unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            return state

        self._forward_events(run, emit)

        collaboration = self._context_payload(run)
        context = dict(state.browser_context)
        context["multi_agent_context"] = collaboration
        context["multi_agent_active"] = True

        advisory = self._advisory_prompt_context(collaboration)
        if advisory:
            original_before = str(context.get("context_before", "") or "").strip()
            context["context_before"] = (
                f"{original_before}\n\n{advisory}" if original_before else advisory
            )

        state.browser_context = context
        state.sync_contract()

        if control is not None:
            control.checkpoint("multi_agent_collaboration_ready")
        return state


__all__ = ["MultiAgentRuntimeBridge"]
