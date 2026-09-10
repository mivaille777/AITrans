from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentCancelledError
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentEvidenceItem,
    AgentPlanContext,
    AgentPlanStep,
    AgentRouteDecision,
)
from backend.services.agent_conversation_service import AgentConversationService

_UI_MODE_BY_TOOL = {
    "translate_selection": "translation",
    "explain_selection": "explanation",
    "summarize_selection": "summary",
    "analyze_section_role": "research",
    "polish_selection": "assistant",
    "save_research_note": "note",
    "inspect_reading_context": "assistant",
    "search_research_notes": "research",
    "search_research_memory": "research",
    "search_knowledge_base": "research",
}


def _structured(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if is_dataclass(value):
        dumped = asdict(value)
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def _scope_values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        identifier = str(item or "").strip()
        if not identifier or identifier in seen:
            continue
        normalized.append(identifier)
        seen.add(identifier)
        if len(normalized) >= 100:
            break
    return normalized


class ProductAgentRuntimeAdapter:
    """Compatibility/projection bridge between ProductAgentService and AgentState."""

    def __init__(
        self,
        service: Any,
        conversation_service: AgentConversationService | Any | None = None,
    ) -> None:
        self._service = service
        self._conversation_service = conversation_service

    @staticmethod
    def build_payload(state: AgentState) -> dict[str, Any]:
        context = state.browser_context
        confirmed = context.get("confirmed_write_tools", ())
        if not isinstance(confirmed, (list, tuple, set, frozenset)):
            confirmed = ()
        history = tuple(
            (item.role, item.content)
            for item in state.conversation.history
            if item.role in {"user", "assistant"} and item.content.strip()
        )
        return {
            "session_id": state.session_id or "agent-session",
            "user_message": state.user_input,
            "context_mode": str(context.get("context_mode", "reading") or "reading"),
            "source_text": state.selected_text,
            "translated_text": str(context.get("translated_text", "") or ""),
            "source_language": str(context.get("source_language", "auto") or "auto"),
            "target_language": str(context.get("target_language", "zh-CN") or "zh-CN"),
            "resource_url": str(context.get("resource_url", "") or ""),
            "resource_title": str(context.get("resource_title", "") or ""),
            "section_heading": str(context.get("section_heading", "") or ""),
            "context_before": str(context.get("context_before", "") or ""),
            "context_after": str(context.get("context_after", "") or ""),
            "source_kind": str(context.get("source_kind", "desktop") or "desktop"),
            "style": str(context.get("style", "academic") or "academic"),
            "workspace_id": str(context.get("workspace_id", "") or "").strip(),
            "conversation_id": state.conversation.conversation_id,
            "history": history,
            "confirmed_write_tools": [str(item) for item in confirmed if str(item).strip()],
            "knowledge_document_ids": _scope_values(context.get("knowledge_document_ids", ())),
            "research_source_ids": _scope_values(context.get("research_source_ids", ())),
            "request_id": max(0, int(context.get("request_id", 0) or 0)),
        }

    _payload = build_payload

    @staticmethod
    def _apply_grounding(state: AgentState, result: Any) -> None:
        if hasattr(result, "evidence"):
            state.evidence = [
                item
                if isinstance(item, AgentEvidenceItem)
                else AgentEvidenceItem.model_validate(item)
                for item in (getattr(result, "evidence", ()) or ())
            ]
        if hasattr(result, "citations"):
            state.citations = [
                item
                if isinstance(item, AgentCitationRef)
                else AgentCitationRef.model_validate(item)
                for item in (getattr(result, "citations", ()) or ())
            ]

    @staticmethod
    def apply_result(state: AgentState, result: Any) -> AgentState:
        plan = _structured(result.plan)
        state.apply_plan(plan)

        route = _structured(getattr(result, "route", None))
        if route:
            state.apply_route(route)
        else:
            action = str(plan.get("action", "answer") or "answer")
            tool_name = str(plan.get("tool_name", "") or "")
            state.intent = tool_name if action == "tool" and tool_name else "answer"

        tool_name = str(plan.get("tool_name", "") or "")
        if tool_name:
            state.record_tool_call(
                {
                    "name": tool_name,
                    "arguments": dict(plan.get("arguments", {}) or {}),
                }
            )

        tool_result = getattr(result, "tool_result", None)
        if tool_result is not None:
            state.record_tool_result(_structured(tool_result))
        ProductAgentRuntimeAdapter._apply_grounding(state, result)

        state.ui_mode = _UI_MODE_BY_TOOL.get(tool_name, "assistant")
        state.apply_response(
            {
                "status": str(getattr(result, "status", "completed") or "completed"),
                "output_text": str(getattr(result, "output_text", "") or ""),
                "provider": str(getattr(result, "provider", "") or ""),
                "model": str(getattr(result, "model", "") or ""),
                "request_id": max(0, int(getattr(result, "request_id", 0) or 0)),
            }
        )
        return state

    _apply_result = apply_result

    @staticmethod
    def _event_forwarder(
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None,
    ) -> tuple[set[AgentEventType], Callable[[str, dict[str, Any]], None]]:
        emitted: set[AgentEventType] = set()

        def forward(event_type: str, payload: dict[str, Any]) -> None:
            try:
                core_type = AgentEventType(event_type)
            except ValueError:
                return
            emitted.add(core_type)
            if emit is not None:
                emit(core_type, payload)

        return emitted, forward

    def begin_conversation(self, state: AgentState):
        service = self._conversation_service
        if service is None:
            return None
        run = service.begin(state)
        service.apply_to_state(state, run)
        return run

    _begin_conversation = begin_conversation

    def complete_conversation(self, run: Any, state: AgentState) -> None:
        if run is not None and self._conversation_service is not None:
            self._conversation_service.complete(run, state)

    _complete_conversation = complete_conversation

    def abort_conversation(self, run: Any, exc: Exception) -> None:
        if run is None or self._conversation_service is None:
            return
        if isinstance(exc, AgentCancelledError):
            self._conversation_service.cancel(run)
        else:
            self._conversation_service.fail(run, exc)

    _abort_conversation = abort_conversation

    def resolve_route(
        self,
        state: AgentState,
        *,
        control: AgentRunControl | None = None,
    ) -> tuple[AgentRouteDecision, dict[str, Any]]:
        resolve = getattr(self._service, "resolve_route", None)
        if callable(resolve):
            route, metadata = resolve(
                control=control,
                **self.build_payload(state),
            )
        else:
            route = AgentRouteDecision(
                kind="answer",
                source="legacy_planner",
                intent="answer",
                user_visible_reason="Compatibility direct route.",
            )
            metadata = {
                "duration_ms": 0,
                "provider": "",
                "model": "",
                "prompt_id": "",
                "llm_called": False,
            }
        state.apply_route(route)
        return route, dict(metadata)

    def plan_multi_step(
        self,
        state: AgentState,
        *,
        control: AgentRunControl | None = None,
    ) -> tuple[AgentPlanContext, dict[str, Any]]:
        plan, metadata = self._service.plan_multi_step(
            control=control,
            **self.build_payload(state),
        )
        state.apply_multi_step_plan(plan)
        return plan, dict(metadata)

    def execute_product(
        self,
        state: AgentState,
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None = None,
        *,
        control: AgentRunControl | None = None,
        resolved_route: AgentRouteDecision | dict[str, Any] | None = None,
        route_metadata: dict[str, Any] | None = None,
    ) -> tuple[AgentState, set[AgentEventType]]:
        emitted, forward = self._event_forwarder(emit)
        payload = self.build_payload(state)
        if resolved_route is not None:
            payload["_resolved_route"] = (
                resolved_route.model_dump()
                if isinstance(resolved_route, AgentRouteDecision)
                else dict(resolved_route)
            )
            payload["_route_metadata"] = dict(route_metadata or {})
        result = self._service.run(
            event_sink=forward,
            control=control,
            **payload,
        )
        return self.apply_result(state, result), emitted

    def execute_plan_step(
        self,
        state: AgentState,
        step: AgentPlanStep,
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None = None,
        *,
        control: AgentRunControl | None = None,
    ) -> tuple[AgentState, set[AgentEventType]]:
        emitted, forward = self._event_forwarder(emit)
        route = AgentRouteDecision(
            kind="tool",
            source="planner",
            intent=step.tool_name,
            tool_name=step.tool_name,
            user_visible_reason=f"Execute {step.step_id}.",
            arguments={str(key): str(value) for key, value in step.arguments.items()},
        )
        payload = self.build_payload(state)
        payload.update(
            {
                "_resolved_route": route.model_dump(),
                "_route_metadata": {
                    "duration_ms": 0,
                    "provider": "",
                    "model": "",
                    "prompt_id": "",
                    "llm_called": False,
                },
                "_suppress_plan_event": True,
                "_skip_synthesis": True,
            }
        )
        result = self._service.run(
            event_sink=forward,
            control=control,
            **payload,
        )

        state.record_tool_call(
            {
                "name": step.tool_name,
                "arguments": dict(step.arguments),
                "step_id": step.step_id,
            }
        )
        if str(getattr(result, "status", "") or "") == "confirmation_required":
            state.ui_mode = _UI_MODE_BY_TOOL.get(step.tool_name, "assistant")
            state.apply_response(
                {
                    "status": "confirmation_required",
                    "output_text": "",
                    "provider": "",
                    "model": "",
                    "request_id": max(0, int(getattr(result, "request_id", 0) or 0)),
                }
            )
            return state, emitted

        tool_result = getattr(result, "tool_result", None)
        if tool_result is None:
            raise RuntimeError(f"Plan step {step.step_id} completed without a tool result.")
        structured = _structured(tool_result)
        structured["step_id"] = step.step_id
        state.record_tool_result(structured)
        self._apply_grounding(state, result)
        state.ui_mode = _UI_MODE_BY_TOOL.get(step.tool_name, "assistant")
        return state, emitted

    def synthesize_multi_step(
        self,
        state: AgentState,
        emit: Callable[[AgentEventType, dict[str, Any]], None] | None = None,
        *,
        control: AgentRunControl | None = None,
    ) -> tuple[AgentState, set[AgentEventType]]:
        emitted, forward = self._event_forwarder(emit)
        result = self._service.synthesize_multi_step(
            tool_results=list(state.tool_results),
            event_sink=forward,
            control=control,
            **self.build_payload(state),
        )
        state.ui_mode = "assistant"
        self._apply_grounding(state, result)
        state.apply_response(
            {
                "status": str(getattr(result, "status", "completed") or "completed"),
                "output_text": str(getattr(result, "output_text", "") or ""),
                "provider": str(getattr(result, "provider", "") or ""),
                "model": str(getattr(result, "model", "") or ""),
                "request_id": max(0, int(getattr(result, "request_id", 0) or 0)),
            }
        )
        return state, emitted

    @staticmethod
    def emit_compatibility_events(
        state: AgentState,
        emitted: set[AgentEventType],
        emit: Callable[[AgentEventType, dict[str, Any]], None],
    ) -> None:
        if AgentEventType.PLAN_READY not in emitted:
            payload: dict[str, Any]
            if state.plan.mode == "multi_step":
                payload = {
                    "mode": "multi_step",
                    "goal": state.plan.goal,
                    "steps": [step.model_dump(mode="json") for step in state.plan.steps],
                    "route_kind": state.route.kind,
                    "route_source": state.route.source,
                }
            else:
                payload = dict(state.planned_action)
            emit(AgentEventType.PLAN_READY, payload)
        if state.tool_calls and AgentEventType.TOOL_CALL not in emitted:
            emit(AgentEventType.TOOL_CALL, dict(state.tool_calls[-1]))
        if state.tool_results and AgentEventType.TOOL_RESULT not in emitted:
            emit(AgentEventType.TOOL_RESULT, dict(state.tool_results[-1]))

    def __call__(self, state: AgentState) -> AgentState:
        conversation_run = self.begin_conversation(state)
        try:
            result = self._service.run(**self.build_payload(state))
            state = self.apply_result(state, result)
            self.complete_conversation(conversation_run, state)
            return state
        except Exception as exc:
            self.abort_conversation(conversation_run, exc)
            raise

    def run_with_events(
        self,
        state: AgentState,
        emit: Callable[[AgentEventType, dict[str, Any]], None],
        *,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        conversation_run = self.begin_conversation(state)
        try:
            state, emitted = self.execute_product(state, emit, control=control)
            self.complete_conversation(conversation_run, state)
        except Exception as exc:
            self.abort_conversation(conversation_run, exc)
            raise

        self.emit_compatibility_events(state, emitted, emit)
        return state

    def close(self) -> None:
        close = getattr(self._service, "close", None)
        if callable(close):
            close()


__all__ = ["ProductAgentRuntimeAdapter"]
