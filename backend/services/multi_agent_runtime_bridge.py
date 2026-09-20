from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentBudgetExceededError, AgentCancelledError
from backend.agent_core.orchestration.parallel_executor import TaskRunLeaseError
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import AgentState
from backend.models.agent_orchestration import OrchestrationLane
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService

CoreEventSink = Callable[[AgentEventType, dict[str, Any]], None]
_MAX_COLLAB_CONTEXT_CHARS = 6000
_MAX_SPECIALIST_OUTPUT_CHARS = 1500
_LANGUAGE_TERMS = ("翻译", "translate", "润色", "polish", "改写", "rewrite")
_SUMMARY_TERMS = ("总结", "摘要", "概括", "summarize", "summary", "abstract")

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
    "task_planned": AgentEventType.TASK_PLANNED,
    "task_ready": AgentEventType.TASK_READY,
    "task_started": AgentEventType.TASK_STARTED,
    "task_progress": AgentEventType.TASK_PROGRESS,
    "task_completed": AgentEventType.TASK_COMPLETED,
    "task_partial": AgentEventType.TASK_PARTIAL,
    "task_failed": AgentEventType.TASK_FAILED,
    "task_blocked": AgentEventType.TASK_BLOCKED,
    "task_cancelled": AgentEventType.TASK_CANCELLED,
    "task_skipped": AgentEventType.TASK_SKIPPED,
    "task_retrying": AgentEventType.TASK_RETRYING,
    "plan_revised": AgentEventType.PLAN_REVISED,
    "budget_exhausted": AgentEventType.BUDGET_EXHAUSTED,
    "artifact_verified": AgentEventType.ARTIFACT_VERIFIED,
    "artifact_rejected": AgentEventType.ARTIFACT_REJECTED,
    "workflow_partial": AgentEventType.WORKFLOW_PARTIAL,
    "workflow_resumed": AgentEventType.WORKFLOW_RESUMED,
}


class MultiAgentRuntimeBridge:
    """Pre-workflow collaboration bridge for the canonical AgentRuntime.

    Specialist outputs are advisory only. The mature ReadingAgentGraph remains
    authoritative for tool execution, ReAct, confirmation, evidence, grounding,
    synthesis, and the final response. Collaboration failure therefore falls
    back to the canonical workflow rather than failing the user's request.
    """

    def __init__(
        self,
        service: MultiAgentWorkspaceService | None = None,
        *,
        orchestrator: Any | None = None,
        maximum_lane: OrchestrationLane = OrchestrationLane.WORKFLOW,
    ) -> None:
        self.service = service or (
            None if orchestrator is not None else MultiAgentWorkspaceService()
        )
        self.orchestrator = orchestrator
        self.maximum_lane = maximum_lane

    def _plan(self, state: AgentState) -> list[dict[str, Any]]:
        if self.service is None:
            return []
        return self.service.planner.create_plan(state.user_input, None)

    def should_run(self, state: AgentState) -> bool:
        mode = (
            str(state.browser_context.get("multi_agent_mode", "auto") or "auto")
            .strip()
            .lower()
        )
        if mode == "off":
            return False
        if self.orchestrator is not None:
            route = self.orchestrator.route(
                state.user_input,
                self._runtime_context(state),
                mode=mode,
            )
            # Force requests the new router, not extra permissions or useless roles.
            if route.lane is OrchestrationLane.FAST:
                return False
            return not (
                self.maximum_lane is OrchestrationLane.SINGLE
                and route.lane is OrchestrationLane.WORKFLOW
            )
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
            MultiAgentRuntimeBridge._forward_event(event, emit)

    @staticmethod
    def _forward_event(event: Any, emit: CoreEventSink) -> None:
        core_type = _EVENT_MAP.get(event.event_type)
        if core_type is None:
            return
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
    def _specialist_output(result: Any) -> dict[str, Any]:
        output = getattr(result, "output", None)
        metadata = getattr(result, "metadata", {}) or {}
        return {
            "agent_name": str(getattr(result, "agent_name", "") or ""),
            "output": output,
            "metadata": dict(metadata) if isinstance(metadata, dict) else {},
        }

    @staticmethod
    def _artifact_language_input(
        user_input: str, output: Any
    ) -> tuple[str, dict[str, Any]] | None:
        normalized = " ".join(str(user_input or "").casefold().split())
        if not (
            any(term in normalized for term in _LANGUAGE_TERMS)
            and any(term in normalized for term in _SUMMARY_TERMS)
        ):
            return None
        if not isinstance(output, dict) or str(output.get("kind", "")) != "document_analysis":
            return None
        content = output.get("content", {})
        reading_card = content.get("reading_card", {}) if isinstance(content, dict) else {}
        if not isinstance(reading_card, dict):
            return None
        labels = (
            ("Research questions", "research_questions"),
            ("Contributions", "contributions"),
            ("Methods", "methods"),
            ("Datasets", "datasets"),
            ("Experiments", "experiments"),
            ("Limitations", "limitations"),
            ("Open questions", "open_questions"),
        )
        lines: list[str] = []
        for label, field in labels:
            raw = reading_card.get(field, output.get(field, ()))
            values = raw if isinstance(raw, list) else [raw]
            cleaned = [str(item).strip() for item in values if str(item).strip()]
            if cleaned:
                lines.append(f"{label}: {'; '.join(cleaned)}")
        text = "\n".join(lines).strip()
        if not text:
            return None
        artifact_ref = {
            key: output.get(key)
            for key in ("artifact_id", "version", "content_hash", "kind")
            if output.get(key) not in {None, ""}
        }
        return text, artifact_ref

    @classmethod
    def _context_payload(cls, run: Any) -> dict[str, Any]:
        if hasattr(run, "task_plan"):
            plan = [dict(item) for item in run.plan]
            outputs = dict(getattr(run, "outputs", {}) or {})
            results = list(getattr(run, "results", ()) or ())
            return {
                "run_id": run.run_id,
                "trace_id": run.trace_id,
                "lane": run.route.lane.value,
                "route": run.route.model_dump(mode="json"),
                "scope_ref": run.scope.scope_ref,
                "plan": plan,
                "agents": [item["agent"] for item in plan],
                "task_results": [item.model_dump(mode="json") for item in results],
                "specialists": [
                    {
                        "task_id": item.task_id,
                        "agent_name": next(
                            (
                                task["agent"]
                                for task in plan
                                if task.get("task_id") == item.task_id
                            ),
                            "",
                        ),
                        "output": outputs.get(item.task_id),
                        "status": item.status.value,
                    }
                    for item in results
                ],
                "specialist_result_count": len(results),
                "total_duration_ms": run.total_duration_ms,
            }
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
            "specialists": [cls._specialist_output(item) for item in run.results],
            "specialist_result_count": len(run.results),
            "total_duration_ms": run.total_duration_ms,
        }

    @staticmethod
    def _advisory_prompt_context(payload: dict[str, Any]) -> str:
        knowledge = str(payload.get("knowledge_context", "") or "").strip()
        agents = [str(item) for item in payload.get("agents", []) if str(item).strip()]
        specialists = payload.get("specialists", [])
        if not knowledge and not agents and not specialists:
            return ""

        lines = [
            "[Multi-Agent collaboration context]",
            "Treat this as advisory context; preserve normal tool, grounding, citation, and safety checks.",
        ]
        if agents:
            lines.append(f"Selected specialist roles: {', '.join(agents)}")
        if knowledge:
            lines.append("Retrieved knowledge:")
            lines.append(knowledge)
        if isinstance(specialists, list):
            for item in specialists:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("agent_name", "specialist") or "specialist")
                output = item.get("output")
                serialized = json.dumps(output, ensure_ascii=False, default=str)
                lines.append(f"{name} specialist output:")
                lines.append(serialized[:_MAX_SPECIALIST_OUTPUT_CHARS])
        return "\n".join(lines)[:_MAX_COLLAB_CONTEXT_CHARS]

    @staticmethod
    def _runtime_context(state: AgentState) -> dict[str, Any]:
        context = state.browser_context
        return {
            "source_text": state.selected_text,
            "source_language": str(context.get("source_language", "auto") or "auto"),
            "target_language": str(context.get("target_language", "zh-CN") or "zh-CN"),
            "resource_url": str(context.get("resource_url", "") or ""),
            "resource_title": str(context.get("resource_title", "") or ""),
            "section_heading": str(context.get("section_heading", "") or ""),
            "workspace_id": str(context.get("workspace_id", "") or "").strip(),
            "knowledge_board_id": str(
                context.get("knowledge_board_id", "") or ""
            ).strip(),
            "knowledge_collection_id": str(
                context.get("knowledge_collection_id", "") or ""
            ).strip(),
            "research_source_ids": list(context.get("research_source_ids", ()) or ()),
            "research_note_ids": list(context.get("research_note_ids", ()) or ()),
            "knowledge_document_ids": list(
                context.get("knowledge_document_ids", ()) or ()
            ),
            "knowledge_item_ids": list(context.get("knowledge_item_ids", ()) or ()),
            "temporary": bool(context.get("temporary", False)),
            "workflow_action": str(context.get("workflow_action", "") or ""),
        }

    def prepare_task_retry(self, state: AgentState, task_id: str) -> tuple[str, ...]:
        if self.orchestrator is None:
            raise ValueError("task retry requires the typed orchestration runtime")
        return tuple(self.orchestrator.prepare_task_retry(state, task_id))

    @staticmethod
    def _apply_memory_projection(
        state: AgentState, memory_snapshot: dict[str, Any]
    ) -> AgentState:
        context = dict(state.browser_context)
        projections = memory_snapshot.get("role_projections", {})
        language_preferences = (
            projections.get("language", []) if isinstance(projections, dict) else []
        )
        context["memory_language_preferences"] = [
            dict(item) for item in language_preferences[:32] if isinstance(item, dict)
        ]
        state.memory_snapshot_ref = str(memory_snapshot.get("snapshot_id", "") or "")
        state.browser_context = context
        state.sync_contract()
        return state

    def prepare_state(self, state: AgentState) -> AgentState:
        if self.orchestrator is None:
            return state
        _scope, memory_snapshot = self.orchestrator.resolve_memory(
            profile_id=str(
                state.browser_context.get("profile_id", "local-default")
                or "local-default"
            ).strip(),
            run_id=state.run_id,
            runtime_context=self._runtime_context(state),
        )
        return self._apply_memory_projection(state, memory_snapshot)

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
            if self.orchestrator is not None:
                run = self.orchestrator.run(
                    state.user_input,
                    profile_id=str(
                        state.browser_context.get("profile_id", "local-default")
                        or "local-default"
                    ).strip(),
                    mode=str(
                        state.browser_context.get("multi_agent_mode", "auto") or "auto"
                    ),
                    run_id=state.run_id,
                    trace_id=state.trace_id,
                    runtime_context=self._runtime_context(state),
                    event_sink=lambda event: self._forward_event(event, emit),
                    control=control,
                )
            else:
                if self.service is None:
                    return state
                run = self.service.run(
                    state.user_input,
                    user_id=state.session_id,
                    run_id=state.run_id,
                    trace_id=state.trace_id,
                    runtime_context=self._runtime_context(state),
                )
        except (AgentCancelledError, AgentBudgetExceededError, TaskRunLeaseError):
            raise
        except Exception as exc:  # noqa: BLE001 - advisory workflow must fall back
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

        if self.orchestrator is None:
            self._forward_events(run, emit)

        collaboration = self._context_payload(run)
        context = dict(state.browser_context)
        context["multi_agent_context"] = collaboration
        context["multi_agent_active"] = True

        if self.orchestrator is not None:
            memory_snapshot = getattr(run, "memory_snapshot", {})
            snapshot_id = str(memory_snapshot.get("snapshot_id", "") or "")
            self._apply_memory_projection(state, memory_snapshot)
            context = dict(state.browser_context)
            context["multi_agent_context"] = collaboration
            context["multi_agent_active"] = True
            task_plan = (
                run.task_plan.model_dump(mode="json")
                if run.task_plan is not None
                else None
            )
            state.apply_orchestration(
                lane=run.route.lane.value,
                status=(
                    "blocked"
                    if run.route.missing_information
                    else "completed"
                    if all(
                        item.status.value in {"succeeded", "partial", "skipped"}
                        for item in run.results
                    )
                    else "partial"
                ),
                scope=run.scope.model_dump(mode="json"),
                plan=task_plan,
                results=[item.model_dump(mode="json") for item in run.results],
                memory_snapshot_ref=snapshot_id,
            )
            context["orchestration_context"] = collaboration
            language_handoff = self._artifact_language_input(
                state.user_input, run.direct_output
            )
            if language_handoff is not None:
                language_input, artifact_ref = language_handoff
                context["derived_language_input"] = language_input
                context["derived_language_input_artifact"] = artifact_ref
                context["orchestration_direct_delivery"] = False
            elif run.direct_delivery and run.direct_output is not None:
                output_text = (
                    run.direct_output
                    if isinstance(run.direct_output, str)
                    else json.dumps(run.direct_output, ensure_ascii=False, default=str)
                )
                state.apply_response(
                    {
                        "status": "completed",
                        "output_text": output_text,
                        "provider": "orchestration-tool",
                        "model": "",
                        "request_id": state.execution.request_id,
                    }
                )
                context["orchestration_direct_delivery"] = True
            state.browser_context = context
            state.sync_contract()
            if control is not None:
                control.checkpoint("multi_agent_collaboration_ready")
            return state

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
