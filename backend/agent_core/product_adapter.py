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
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
    KnowledgeScopeStrategy,
    ResolvedKnowledgeScope,
)
from backend.services.agent_conversation_service import AgentConversationService
from backend.services.knowledge_access_router import KnowledgeAccessRouter
from backend.services.knowledge_scope_resolver import KnowledgeScopeResolver

_UI_MODE_BY_TOOL = {
    "translate_selection": "translation",
    "explain_selection": "explanation",
    "summarize_selection": "summary",
    "analyze_section_role": "research",
    "polish_selection": "assistant",
    "save_research_note": "note",
    "save_knowledge_card": "note",
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


def _latest_tool_output(state: AgentState) -> str:
    for result in reversed(state.tool_results):
        output = str(result.get("output_text", "") or "").strip()
        tool_name = str(result.get("tool_name", "") or "").strip()
        if output and tool_name != "save_knowledge_card":
            return output[:50_000]
    return ""


class ProductAgentRuntimeAdapter:
    """Compatibility/projection bridge between ProductAgentService and AgentState."""

    def __init__(
        self,
        service: Any,
        conversation_service: AgentConversationService | Any | None = None,
        knowledge_access_router: KnowledgeAccessRouter | Any | None = None,
    ) -> None:
        self._service = service
        self._conversation_service = conversation_service
        self._knowledge_access_router = knowledge_access_router or KnowledgeAccessRouter()

    @staticmethod
    def build_payload(state: AgentState) -> dict[str, Any]:
        context = state.browser_context
        derived_language_input = str(
            context.get("derived_language_input", "") or ""
        ).strip()
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
            "run_id": state.run_id,
            "trace_id": state.trace_id,
            "user_message": state.user_input,
            "context_mode": str(context.get("context_mode", "reading") or "reading"),
            "knowledge_access_policy": str(
                context.get("knowledge_access_policy", state.knowledge_policy.value)
                or state.knowledge_policy.value
            ),
            "knowledge_enabled": context.get("knowledge_enabled"),
            "source_text": derived_language_input or state.selected_text,
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
            "enabled_tools": _scope_values(context.get("enabled_tools", ())),
            "disabled_tools": _scope_values(context.get("disabled_tools", ())),
            "knowledge_document_ids": _scope_values(context.get("knowledge_document_ids", ())),
            "explicit_knowledge_document_ids": _scope_values(
                context.get("explicit_knowledge_document_ids", ())
            ),
            "attached_document_id": str(
                context.get("attached_document_id", "") or ""
            ).strip(),
            "knowledge_scope_strategy": str(
                context.get("knowledge_scope_strategy", "none") or "none"
            ),
            "knowledge_scope_allow_global": bool(
                context.get("knowledge_scope_allow_global", False)
            ),
            "research_source_ids": _scope_values(context.get("research_source_ids", ())),
            "knowledge_context": _structured(context.get("knowledge_context")),
            "memory_language_preferences": [
                dict(item)
                for item in context.get("memory_language_preferences", ())[:32]
                if isinstance(item, dict)
            ]
            if isinstance(context.get("memory_language_preferences"), list)
            else [],
            "knowledge_item_id": str(context.get("knowledge_item_id", "") or "").strip(),
            "knowledge_writeback_type": str(context.get("knowledge_writeback_type", "") or "").strip(),
            "knowledge_writeback_operation": str(context.get("knowledge_writeback_operation", "") or "").strip(),
            "knowledge_relation_type": str(context.get("knowledge_relation_type", "") or "").strip(),
            "ai_content": _latest_tool_output(state),
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
        if bool(state.browser_context.get("temporary", False)):
            state.conversation.conversation_id = ""
            state.conversation.history = []
            return None
        service = self._conversation_service
        if service is None:
            return None
        run = service.begin(state)
        service.apply_to_state(state, run)
        return run

    _begin_conversation = begin_conversation

    def resolve_knowledge_access(self, state: AgentState) -> KnowledgeAccessDecision:
        if state.knowledge_decision is not None:
            return state.knowledge_decision

        payload = self.build_payload(state)
        context = state.browser_context
        explicit_ids = payload.get("explicit_knowledge_document_ids", ())
        if not explicit_ids and not str(payload.get("workspace_id", "") or "").strip():
            explicit_ids = payload.get("knowledge_document_ids", ())
        attached_document = str(
            payload.get("attached_document_id", "") or ""
        ).strip()
        decision = self._knowledge_access_router.route(
            user_message=str(payload.get("user_message", "") or ""),
            context_mode=str(payload.get("context_mode", "general") or "general"),
            policy=str(
                payload.get("knowledge_access_policy", KnowledgeAccessPolicy.AUTO.value)
                or KnowledgeAccessPolicy.AUTO.value
            ),
            reading_context_available=bool(
                str(payload.get("source_text", "") or "").strip()
                or str(payload.get("context_before", "") or "").strip()
                or str(payload.get("context_after", "") or "").strip()
            ),
            attached_document=attached_document,
            explicit_scope_count=len(explicit_ids or ()),
            workspace_available=bool(
                str(
                    context.get("active_research_workspace_id", "")
                    or context.get("workspace_id", "")
                    or ""
                ).strip()
            ),
            knowledge_available=bool(context.get("knowledge_available", True)),
            context_summary=" · ".join(
                item
                for item in (
                    str(payload.get("resource_title", "") or "").strip(),
                    str(payload.get("section_heading", "") or "").strip(),
                )
                if item
            )[:1_000],
        )
        state.knowledge_policy = decision.mode
        state.knowledge_decision = decision
        context["knowledge_decision"] = decision.model_dump(mode="json")
        if decision.should_retrieve:
            context.pop("disabled_tools", None)
        else:
            context["disabled_tools"] = sorted(self._knowledge_tool_names())
        if (
            bool(decision.should_retrieve)
            and decision.scope_strategy.value == "global_knowledge"
            and not payload.get("knowledge_document_ids")
        ):
            context["knowledge_scope_strategy"] = "global_knowledge"
            context["knowledge_scope_allow_global"] = True
        return decision

    def resolve_knowledge_scope(
        self,
        state: AgentState,
        *,
        decision: KnowledgeAccessDecision | None = None,
    ) -> ResolvedKnowledgeScope:
        resolved_decision = decision or self.resolve_knowledge_access(state)
        context = state.browser_context
        active_workspace_id = str(
            context.get("active_research_workspace_id", "") or ""
        ).strip()
        scope = KnowledgeScopeResolver().resolve(
            context_mode=str(context.get("context_mode", "general") or "general"),
            explicit_document_ids=context.get("explicit_knowledge_document_ids", ()),
            attached_document_id=str(
                context.get("attached_document_id", "") or ""
            ).strip(),
            workspace_id=active_workspace_id
            or str(context.get("workspace_id", "") or "").strip(),
            workspace_document_ids=context.get("knowledge_document_ids", ()),
            research_source_ids=context.get("research_source_ids", ()),
            global_allowed=bool(context.get("knowledge_scope_allow_global", False)),
            requested_strategy=resolved_decision.scope_strategy,
        )
        state.knowledge_scope = scope
        context["knowledge_scope"] = scope.model_dump(mode="json")
        context["knowledge_scope_strategy"] = scope.strategy.value
        context["knowledge_scope_allow_global"] = scope.allow_global
        context["knowledge_scope_reason"] = scope.reason
        context["knowledge_document_ids"] = list(scope.document_ids)
        context["research_source_ids"] = list(scope.research_source_ids)
        context["workspace_id"] = scope.workspace_id
        return scope

    def _knowledge_tool_names(self) -> set[str]:
        registry = getattr(self._service, "_registry", None)
        list_tools = getattr(registry, "list_tools", None)
        if not callable(list_tools):
            return set()
        return {
            str(getattr(item, "name", "") or "")
            for item in list_tools()
            if str(getattr(item, "name", "") or "")
            in {
                "search_knowledge_base",
                "search_research_notes",
                "search_research_memory",
                "analyze_cross_document_research",
                "search_evidence_ledger",
            }
        }

    def registered_tools(self, state: AgentState | None = None) -> tuple[Any, ...]:
        """Return tools visible to this run after the knowledge decision."""

        registry = getattr(self._service, "_registry", None)
        list_tools = getattr(registry, "list_tools", None)
        if not callable(list_tools):
            list_tools = getattr(self._service, "list_tools", None)
        if not callable(list_tools):
            return ()
        tools = tuple(list_tools())
        if state is None:
            return tools
        decision = state.browser_context.get("knowledge_decision", {})
        if isinstance(decision, dict) and not bool(decision.get("should_retrieve", False)):
            knowledge_tools = self._knowledge_tool_names()
            return tuple(
                tool
                for tool in tools
                if str(getattr(tool, "name", "") or "") not in knowledge_tools
            )
        return tools

    def _restrict_non_retrieval_tools(
        self,
        payload: dict[str, Any],
        knowledge_tools: set[str],
    ) -> dict[str, Any]:
        if not knowledge_tools:
            return payload
        registry = getattr(self._service, "_registry", None)
        list_tools = getattr(registry, "list_tools", None)
        if not callable(list_tools):
            return payload
        available = [str(getattr(item, "name", "") or "") for item in list_tools()]
        payload["disabled_tools"] = sorted(knowledge_tools)
        selected = payload.get("enabled_tools", ())
        if selected:
            payload["enabled_tools"] = [
                name for name in selected if str(name) not in knowledge_tools
            ]
        else:
            payload["enabled_tools"] = [
                name for name in available if name and name not in knowledge_tools
            ]
        return payload

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
        decision_model = self.resolve_knowledge_access(state)
        self.resolve_knowledge_scope(state, decision=decision_model)
        payload = self.build_payload(state)
        decision = decision_model.model_dump(mode="json")
        knowledge_tools = self._knowledge_tool_names()
        if not bool(decision.get("should_retrieve", False)):
            payload = self._restrict_non_retrieval_tools(payload, knowledge_tools)

        resolve = getattr(self._service, "resolve_route", None)
        if callable(resolve):
            route, metadata = resolve(
                control=control,
                **payload,
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
        if (
            bool(decision.get("should_retrieve", False))
            and str(decision.get("mode", "auto") or "auto") == "always"
            and "search_knowledge_base" in knowledge_tools
            and not (
                route.kind == "tool"
                and route.tool_name in knowledge_tools
            )
        ):
            route = AgentRouteDecision(
                kind="tool",
                source="deterministic",
                intent="search_knowledge_base",
                tool_name="search_knowledge_base",
                user_visible_reason="Knowledge policy is Always; perform the required retrieval first.",
                arguments={"query": str(payload.get("user_message", "") or "")},
            )
        elif (
            bool(decision.get("should_retrieve", False))
            and route.kind == "answer"
            and str(decision.get("reason_code", "") or "")
            in {
                "knowledge_request",
                "cross_document_request",
                "current_context_insufficient",
                "document_grounding_required",
                "research_grounding_required",
            }
            and "search_knowledge_base" in knowledge_tools
        ):
            route = AgentRouteDecision(
                kind="tool",
                source="deterministic",
                intent="search_knowledge_base",
                tool_name="search_knowledge_base",
                user_visible_reason="Knowledge decision requires evidence retrieval.",
                arguments={"query": str(payload.get("user_message", "") or "")},
            )
        metadata = {
            **dict(metadata),
            "knowledge_decision": decision,
            "knowledge_tool_restricted": not bool(
                decision.get("should_retrieve", False)
            ),
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
            route_value = (
                resolved_route
                if isinstance(resolved_route, AgentRouteDecision)
                else AgentRouteDecision.model_validate(resolved_route)
            )
            if route_value.tool_name == "search_knowledge_base":
                state.retrieval_attempt_count += 1
            payload["_resolved_route"] = (
                route_value.model_dump()
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
                "step_id": step.step_id,
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
