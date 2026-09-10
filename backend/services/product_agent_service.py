from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.ai.errors import AIConfigurationError, AIError
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentRuntimeError,
    AgentToolError,
    AgentToolTimeoutError,
)
from backend.agent_core.reliability import AgentRunControl, run_safe_tool_with_timeout
from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentEvidenceItem,
    AgentPlanContext,
    AgentRouteDecision,
)
from backend.models.agent_tools import AgentPlan
from backend.rag.citation_service import CitationService, build_evidence_citations
from backend.rag.observability import RAG_EVENT_TYPES
from backend.services.agent_multi_step_planner_service import (
    AgentMultiStepPlannerService,
)
from backend.services.agent_planner_service import AgentPlannerService
from backend.services.agent_router_service import (
    AgentDeterministicRouterService,
    AgentSemanticRouterService,
)
from backend.services.agent_tool_registry import (
    AgentToolExecutionResult,
    AgentToolRegistry,
)
from backend.services.companion_chat_service import CompanionChatService
from backend.services.grounded_synthesis_service import GroundedSynthesisService

AgentLifecycleSink = Callable[[str, dict[str, Any]], None]
_GROUNDED_RETRIEVAL_TOOLS = frozenset(
    {
        "search_knowledge_base",
        "search_research_notes",
        "search_research_memory",
        "analyze_cross_document_research",
        "search_evidence_ledger",
    }
)


@dataclass(frozen=True, slots=True)
class ProductAgentRunResult:
    status: str
    plan: AgentPlan
    output_text: str = ""
    provider: str = ""
    model: str = ""
    request_id: int = 0
    tool_result: AgentToolExecutionResult | None = None
    route: AgentRouteDecision | None = None
    evidence: tuple[AgentEvidenceItem, ...] = ()
    citations: tuple[AgentCitationRef, ...] = ()


def _duration_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _retryable_tool_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            AIConfigurationError,
            AgentCancelledError,
            AgentBudgetExceededError,
            AgentToolTimeoutError,
        ),
    ):
        return False
    return isinstance(exc, (AIError, OSError, TimeoutError, AgentRuntimeError))


def _route_to_plan(route: AgentRouteDecision) -> AgentPlan:
    if route.kind == "tool" and route.tool_name:
        return AgentPlan(
            action="tool",
            tool_name=route.tool_name,
            user_visible_reason=route.user_visible_reason,
            arguments=dict(route.arguments),
        )
    return AgentPlan(
        action="answer",
        user_visible_reason=route.user_visible_reason,
    )


def _trusted_scope_ids(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        identifier = str(item or "").strip()
        if not identifier or len(identifier) > 256 or identifier in seen:
            continue
        normalized.append(identifier)
        seen.add(identifier)
        if len(normalized) >= limit:
            break
    return normalized


class ProductAgentService:
    """Bounded route/tool/synthesis capabilities used by ReadingAgentGraph.

    The public ``run`` method preserves the Stage 10.3 single-step behavior.
    Stage 10.6 additionally exposes route resolution, bounded multi-step
    planning, forced single-tool execution, and final multi-step synthesis so
    LangGraph can own orchestration without duplicating tool safety logic.
    """

    def __init__(
        self,
        *,
        registry: AgentToolRegistry,
        chat_service: CompanionChatService,
        router: AgentDeterministicRouterService | Any | None = None,
        semantic_router: AgentSemanticRouterService | Any | None = None,
        planner: AgentPlannerService | Any | None = None,
        multi_step_planner: AgentMultiStepPlannerService | Any | None = None,
        grounded_synthesis_service: GroundedSynthesisService | Any | None = None,
    ) -> None:
        self._registry = registry
        self._chat_service = chat_service
        self._router = router or AgentDeterministicRouterService()
        self._semantic_router = semantic_router or planner or AgentSemanticRouterService()
        self._multi_step_planner = multi_step_planner or AgentMultiStepPlannerService()
        self._grounded_synthesis_service = (
            grounded_synthesis_service
            or GroundedSynthesisService(chat_service=chat_service)
        )

    @staticmethod
    def _reading_fields(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_text": payload["source_text"],
            "translated_text": payload.get("translated_text", ""),
            "source_language": payload.get("source_language", "auto"),
            "target_language": payload.get("target_language", "zh-CN"),
            "resource_url": payload.get("resource_url", ""),
            "resource_title": payload.get("resource_title", ""),
            "section_heading": payload.get("section_heading", ""),
            "context_before": payload.get("context_before", ""),
            "context_after": payload.get("context_after", ""),
            "source_kind": payload.get("source_kind", "desktop"),
        }

    @staticmethod
    def _conversation_history(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        raw = payload.get("history", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        history: list[tuple[str, str]] = []
        for item in raw:
            if isinstance(item, dict):
                role = str(item.get("role", "") or "").strip()
                content = str(item.get("content", "") or "").strip()
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                role = str(item[0] or "").strip()
                content = str(item[1] or "").strip()
            else:
                continue
            if role not in {"user", "assistant"} or not content:
                continue
            history.append((role, content))
        return tuple(history[-32:])

    @staticmethod
    def _chat_context_mode(payload: dict[str, Any]) -> str:
        """Map Agent execution domains onto the chat core's General/Reading modes."""
        mode = str(payload.get("context_mode", "reading") or "reading").strip().lower()
        return "reading" if mode in {"reading", "translation"} else "general"

    @staticmethod
    def _emit(
        sink: AgentLifecycleSink | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if sink is not None:
            sink(event_type, payload)

    def _semantic_route(
        self,
        *,
        tools,
        payload: dict[str, Any],
    ) -> AgentRouteDecision:
        route = getattr(self._semantic_router, "route", None)
        if callable(route):
            return route(tools=tools, **payload)
        plan = self._semantic_router.plan(tools=tools, **payload)
        if plan.action == "tool":
            return AgentRouteDecision(
                kind="tool",
                source="legacy_planner",
                intent=plan.tool_name,
                tool_name=plan.tool_name,
                user_visible_reason=plan.user_visible_reason,
                arguments=dict(plan.arguments),
            )
        return AgentRouteDecision(
            kind="answer",
            source="legacy_planner",
            intent="answer",
            user_visible_reason=plan.user_visible_reason,
        )

    def _resolve_route(
        self,
        *,
        control: AgentRunControl,
        tools,
        user_message: str,
        reading: dict[str, Any],
        history: tuple[tuple[str, str], ...],
    ) -> tuple[AgentRouteDecision, dict[str, Any]]:
        control.checkpoint("deterministic_route")
        deterministic_started = monotonic()
        route = self._router.route(user_message=user_message, tools=tools)
        if route.kind != "unresolved":
            control.checkpoint("deterministic_route_result")
            return route, {
                "duration_ms": _duration_ms(deterministic_started),
                "provider": "",
                "model": "",
                "prompt_id": "",
                "llm_called": False,
            }

        control.checkpoint("semantic_router")
        semantic_started = monotonic()
        semantic_payload = {
            "user_message": user_message,
            "source_text": str(reading["source_text"]),
            "translated_text": str(reading["translated_text"]),
            "resource_url": str(reading["resource_url"]),
            "resource_title": str(reading["resource_title"]),
            "section_heading": str(reading["section_heading"]),
            "context_before": str(reading["context_before"]),
            "context_after": str(reading["context_after"]),
            "source_kind": str(reading["source_kind"]),
            "history": history,
        }
        route = self._semantic_route(tools=tools, payload=semantic_payload)
        control.checkpoint("semantic_router_result")
        return route, {
            "duration_ms": _duration_ms(semantic_started),
            "provider": str(getattr(self._semantic_router, "provider_name", "") or ""),
            "model": str(getattr(self._semantic_router, "model", "") or ""),
            "prompt_id": str(getattr(self._semantic_router, "prompt_id", "") or ""),
            "llm_called": route.kind != "complex",
        }

    def resolve_route(
        self,
        *,
        control: AgentRunControl | None = None,
        **payload: Any,
    ) -> tuple[AgentRouteDecision, dict[str, Any]]:
        active_control = control or AgentRunControl()
        reading = self._reading_fields(payload)
        history = self._conversation_history(payload)
        return self._resolve_route(
            control=active_control,
            tools=self._registry.list_tools(),
            user_message=str(payload["user_message"]),
            reading=reading,
            history=history,
        )

    def plan_multi_step(
        self,
        *,
        control: AgentRunControl | None = None,
        **payload: Any,
    ) -> tuple[AgentPlanContext, dict[str, Any]]:
        active_control = control or AgentRunControl()
        active_control.checkpoint("multi_step_planner")
        started = monotonic()
        reading = self._reading_fields(payload)
        history = self._conversation_history(payload)
        plan = self._multi_step_planner.plan(
            tools=self._registry.list_tools(),
            max_steps=min(active_control.policy.max_plan_steps, active_control.policy.max_tool_calls),
            user_message=str(payload["user_message"]),
            history=history,
            **reading,
        )
        active_control.checkpoint("multi_step_planner_result")
        return plan, {
            "duration_ms": _duration_ms(started),
            "provider": str(getattr(self._multi_step_planner, "provider_name", "") or ""),
            "model": str(getattr(self._multi_step_planner, "model", "") or ""),
            "prompt_id": str(getattr(self._multi_step_planner, "prompt_id", "") or ""),
            "llm_called": True,
        }

    def _validated_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, str]:
        validate = getattr(self._registry, "validate_planner_arguments", None)
        if callable(validate):
            return validate(tool_name, arguments)
        return {str(key): str(value) for key, value in dict(arguments or {}).items()}

    def _allows_safe_retry(self, tool_name: str, *, effect: str) -> bool:
        allows = getattr(self._registry, "allows_safe_retry", None)
        if callable(allows):
            return bool(allows(tool_name))
        return effect != "write"

    def _execute_tool(
        self,
        *,
        plan: AgentPlan,
        route: AgentRouteDecision,
        reading: dict[str, Any],
        payload: dict[str, Any],
        control: AgentRunControl,
        event_sink: AgentLifecycleSink | None,
        request_id: int,
    ) -> tuple[AgentToolExecutionResult | None, bool]:
        spec = self._registry.get_tool(plan.tool_name)
        if spec is None:
            raise RuntimeError(f"Validated route references missing tool: {plan.tool_name}")

        self._emit(
            event_sink,
            "tool_call",
            {
                "name": spec.name,
                "arguments": dict(plan.arguments),
                "effect": spec.effect,
                "requires_confirmation": spec.requires_confirmation,
                "route_source": route.source,
                "request_id": request_id,
            },
        )

        confirmed = {
            str(item).strip()
            for item in payload.get("confirmed_write_tools", ())
            if str(item).strip()
        }
        if spec.effect == "write" and spec.requires_confirmation and spec.name not in confirmed:
            return None, True

        try:
            validated_arguments = self._validated_arguments(spec.name, plan.arguments)
        except (KeyError, ValueError) as exc:
            raise AgentToolError(
                f"Agent tool {spec.name} received invalid route arguments: {exc}",
                stage="tool",
                fallback_reason="invalid_tool_arguments",
            ) from exc

        execution_payload = {
            **reading,
            "style": str(payload.get("style", "academic") or "academic"),
            "conversation_id": str(payload.get("conversation_id", "") or ""),
            "request_id": request_id,
            **validated_arguments,
        }
        workspace_id = str(payload.get("workspace_id", "") or "").strip()
        if workspace_id:
            execution_payload["workspace_id"] = workspace_id
        if spec.name == "search_knowledge_base":
            trusted_document_ids = _trusted_scope_ids(payload.get("knowledge_document_ids", ()))
            if trusted_document_ids:
                execution_payload["document_ids"] = trusted_document_ids
                execution_payload["document_scope"] = ""
        elif spec.name == "search_research_notes":
            trusted_source_ids = _trusted_scope_ids(payload.get("research_source_ids", ()))
            if trusted_source_ids:
                execution_payload["source_ids"] = trusted_source_ids

        tool_started = monotonic()
        if spec.effect == "write":
            control.checkpoint(f"write_tool:{spec.name}")
            tool_result = self._registry.execute(spec.name, **execution_payload)
        elif not self._allows_safe_retry(spec.name, effect=spec.effect):
            control.checkpoint(f"tool:{spec.name}")
            tool_result = self._registry.execute(spec.name, **execution_payload)
        else:
            max_attempts = 1 + control.policy.max_safe_retries
            tool_result: AgentToolExecutionResult | None = None
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                control.checkpoint(f"tool:{spec.name}:attempt:{attempt}")
                try:
                    tool_result = run_safe_tool_with_timeout(
                        lambda: self._registry.execute(spec.name, **execution_payload),
                        control=control,
                        tool_name=spec.name,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    retryable = _retryable_tool_error(exc)
                    if not retryable or attempt >= max_attempts:
                        if isinstance(exc, AgentRuntimeError):
                            raise
                        raise AgentToolError(
                            f"Agent tool {spec.name} failed after {attempt} attempt(s): {exc}",
                            stage="tool",
                            fallback_reason=(
                                "safe_tool_retries_exhausted"
                                if retryable
                                else "tool_failure_not_retryable"
                            ),
                        ) from exc
                    self._emit(
                        event_sink,
                        "retry",
                        {
                            "tool_name": spec.name,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "reason": str(exc) or type(exc).__name__,
                            "request_id": request_id,
                        },
                    )
            if tool_result is None:
                raise AgentToolError(
                    f"Agent tool {spec.name} failed without a result: {last_error}",
                    stage="tool",
                    fallback_reason="safe_tool_retries_exhausted",
                )

        if tool_result.tool_name == "search_knowledge_base":
            seen_rag_events: set[str] = set()
            for raw_event in (tool_result.data or {}).get("observability", []):
                if not isinstance(raw_event, dict):
                    continue
                event_type = str(raw_event.get("event_type", "") or "")
                payload_data = raw_event.get("payload", {})
                if (
                    event_type not in RAG_EVENT_TYPES
                    or event_type in seen_rag_events
                    or not isinstance(payload_data, dict)
                ):
                    continue
                seen_rag_events.add(event_type)
                self._emit(event_sink, event_type, dict(payload_data))

        trace_data = (
            {}
            if tool_result.tool_name in _GROUNDED_RETRIEVAL_TOOLS
            else tool_result.data or {}
        )
        self._emit(
            event_sink,
            "tool_result",
            {
                "tool_name": tool_result.tool_name,
                "output_text": tool_result.output_text,
                "effect": tool_result.effect,
                "provider": tool_result.provider,
                "model": tool_result.model,
                "request_id": tool_result.request_id,
                "data": trace_data,
                "duration_ms": _duration_ms(tool_started),
            },
        )
        return tool_result, False

    @staticmethod
    def _retrieval_grounding(
        data: dict[str, Any] | None,
    ) -> tuple[list[AgentEvidenceItem], list[AgentCitationRef]]:
        payload = dict(data or {})
        try:
            evidence = [
                AgentEvidenceItem.model_validate(item)
                for item in payload.get("evidence", [])
            ]
            citations = [
                AgentCitationRef.model_validate(item)
                for item in payload.get("citations", [])
            ]
            CitationService().validate(citations, evidence)
        except Exception as exc:
            raise AgentToolError(
                f"Retrieval tool returned invalid evidence or citations: {exc}",
                stage="synthesis",
                fallback_reason="invalid_retrieval_citations",
            ) from exc
        return evidence, citations

    _knowledge_grounding = _retrieval_grounding

    def _synthesize_grounded(
        self,
        *,
        payload: dict[str, Any],
        reading: dict[str, Any],
        history: tuple[tuple[str, str], ...],
        request_id: int,
        control: AgentRunControl,
        event_sink: AgentLifecycleSink | None,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
    ):
        control.checkpoint("synthesis")
        started = monotonic()
        verified = self._grounded_synthesis_service.send_verified(
            session_id=str(payload.get("session_id", "agent-session")),
            user_message=str(payload["user_message"]),
            **reading,
            history=history,
            request_id=request_id,
            context_mode=self._chat_context_mode(payload),
            evidence=evidence,
            citations=citations,
        )
        answer = verified.answer
        verification = verified.verification
        if verification is not None:
            self._emit(
                event_sink,
                "grounding_verification_evaluated",
                {
                    "passed": verification.passed,
                    "fallback_applied": verified.fallback_applied,
                    "claim_count": verification.claim_count,
                    "cited_claim_count": verification.cited_claim_count,
                    "supported_claim_count": verification.supported_claim_count,
                    "unsupported_claim_count": verification.unsupported_claim_count,
                    "invalid_citation_count": verification.invalid_citation_count,
                    "citation_coverage": verification.citation_coverage,
                    "support_rate": verification.support_rate,
                    "reason_codes": list(verification.reason_codes),
                    "request_id": answer.request_id,
                },
            )
        control.checkpoint("synthesis_result")
        self._emit(
            event_sink,
            "synthesis_ready",
            {
                "provider": answer.provider,
                "model": answer.model,
                "request_id": answer.request_id,
                "duration_ms": _duration_ms(started),
                "prompt_id": str(
                    getattr(self._grounded_synthesis_service, "prompt_id", "") or ""
                ),
                "grounded": True,
                "evidence_count": len(evidence),
                "citation_count": len(citations),
            },
        )
        return answer

    def _synthesize(
        self,
        *,
        payload: dict[str, Any],
        reading: dict[str, Any],
        history: tuple[tuple[str, str], ...],
        request_id: int,
        control: AgentRunControl,
        event_sink: AgentLifecycleSink | None,
        tool_name: str = "",
        tool_context: str = "",
    ):
        control.checkpoint("synthesis")
        started = monotonic()
        kwargs: dict[str, Any] = {}
        if tool_name:
            kwargs["tool_name"] = tool_name
            kwargs["tool_context"] = tool_context
        answer = self._chat_service.send(
            session_id=str(payload.get("session_id", "agent-session")),
            user_message=str(payload["user_message"]),
            **reading,
            history=history,
            request_id=request_id,
            context_mode=self._chat_context_mode(payload),
            **kwargs,
        )
        control.checkpoint("synthesis_result")
        self._emit(
            event_sink,
            "synthesis_ready",
            {
                "provider": answer.provider,
                "model": answer.model,
                "request_id": answer.request_id,
                "duration_ms": _duration_ms(started),
                "prompt_id": str(getattr(self._chat_service, "prompt_id", "") or ""),
            },
        )
        return answer

    def synthesize_multi_step(
        self,
        *,
        tool_results: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        event_sink: AgentLifecycleSink | None = None,
        control: AgentRunControl | None = None,
        **payload: Any,
    ) -> ProductAgentRunResult:
        active_control = control or AgentRunControl()
        request_id = max(0, int(payload.get("request_id", 0) or 0))
        results = [dict(item) for item in tool_results if isinstance(item, dict)]
        if not results:
            raise AgentToolError(
                "Multi-step synthesis requires at least one completed tool result.",
                stage="synthesis",
                fallback_reason="missing_tool_observations",
            )

        last = results[-1]
        if str(last.get("effect", "") or "") == "write":
            return ProductAgentRunResult(
                status="completed",
                plan=AgentPlan(
                    action="answer",
                    user_visible_reason="Complete the requested multi-step action.",
                ),
                output_text=str(last.get("output_text", "") or ""),
                provider=str(last.get("provider", "") or ""),
                model=str(last.get("model", "") or ""),
                request_id=request_id,
                route=AgentRouteDecision(
                    kind="complex",
                    source="planner",
                    intent="complex",
                    user_visible_reason="Completed the bounded multi-step plan.",
                ),
            )

        reading = self._reading_fields(payload)
        history = self._conversation_history(payload)
        observation = json.dumps(
            {
                "plan_type": "multi_step",
                "observations": [
                    {
                        "tool_name": str(item.get("tool_name", "") or item.get("name", "") or ""),
                        "output_text": str(item.get("output_text", "") or ""),
                        "data": dict(item.get("data", {}) or {}),
                    }
                    for item in results
                ],
            },
            ensure_ascii=False,
        )
        grounded_results = [
            item
            for item in results
            if str(item.get("tool_name", "") or item.get("name", "") or "")
            in _GROUNDED_RETRIEVAL_TOOLS
        ]
        evidence: list[AgentEvidenceItem] = []
        citations: list[AgentCitationRef] = []
        if grounded_results:
            seen_evidence: set[str] = set()
            for item in grounded_results:
                item_evidence, _item_citations = self._retrieval_grounding(
                    dict(item.get("data", {}) or {})
                )
                for evidence_item in item_evidence:
                    if evidence_item.evidence_id not in seen_evidence:
                        evidence.append(evidence_item)
                        seen_evidence.add(evidence_item.evidence_id)
            citations = build_evidence_citations(evidence)
            answer = self._synthesize_grounded(
                payload=payload,
                reading=reading,
                history=history,
                request_id=request_id,
                control=active_control,
                event_sink=event_sink,
                evidence=evidence,
                citations=citations,
            )
        else:
            answer = self._synthesize(
                payload=payload,
                reading=reading,
                history=history,
                request_id=request_id,
                control=active_control,
                event_sink=event_sink,
                tool_name="multi_step_plan",
                tool_context=observation,
            )
        return ProductAgentRunResult(
            status="completed",
            plan=AgentPlan(
                action="answer",
                user_visible_reason="Synthesize the completed multi-step tool observations.",
            ),
            output_text=answer.output_text,
            provider=answer.provider,
            model=answer.model,
            request_id=answer.request_id,
            route=AgentRouteDecision(
                kind="complex",
                source="planner",
                intent="complex",
                user_visible_reason="Completed the bounded multi-step plan.",
            ),
            evidence=tuple(evidence),
            citations=tuple(citations),
        )

    def run(
        self,
        *,
        event_sink: AgentLifecycleSink | None = None,
        control: AgentRunControl | None = None,
        **payload: Any,
    ) -> ProductAgentRunResult:
        control = control or AgentRunControl()
        reading = self._reading_fields(payload)
        history = self._conversation_history(payload)
        request_id = max(0, int(payload.get("request_id", 0) or 0))

        forced_route = payload.pop("_resolved_route", None)
        route_metadata = dict(payload.pop("_route_metadata", {}) or {})
        suppress_plan_event = bool(payload.pop("_suppress_plan_event", False))
        skip_synthesis = bool(payload.pop("_skip_synthesis", False))

        if forced_route is not None:
            route = (
                forced_route
                if isinstance(forced_route, AgentRouteDecision)
                else AgentRouteDecision.model_validate(forced_route)
            )
        else:
            route, route_metadata = self.resolve_route(control=control, **payload)

        if route.kind == "complex":
            raise AgentRuntimeError(
                "Complex Agent route requires ReadingAgentGraph multi-step orchestration.",
                stage="planner",
                fallback_reason="complex_route_requires_graph",
            )

        plan = _route_to_plan(route)
        if not suppress_plan_event:
            self._emit(
                event_sink,
                "plan_ready",
                {
                    "action": plan.action,
                    "tool_name": plan.tool_name,
                    "user_visible_reason": plan.user_visible_reason,
                    "arguments": dict(plan.arguments),
                    "route_kind": route.kind,
                    "route_source": route.source,
                    "request_id": request_id,
                    **route_metadata,
                },
            )

        if plan.action == "answer":
            answer = self._synthesize(
                payload=payload,
                reading=reading,
                history=history,
                request_id=request_id,
                control=control,
                event_sink=event_sink,
            )
            return ProductAgentRunResult(
                status="completed",
                plan=plan,
                output_text=answer.output_text,
                provider=answer.provider,
                model=answer.model,
                request_id=answer.request_id,
                route=route,
            )

        tool_result, confirmation_required = self._execute_tool(
            plan=plan,
            route=route,
            reading=reading,
            payload=payload,
            control=control,
            event_sink=event_sink,
            request_id=request_id,
        )
        if confirmation_required:
            return ProductAgentRunResult(
                status="confirmation_required",
                plan=plan,
                request_id=request_id,
                route=route,
            )
        if tool_result is None:
            raise AgentToolError(
                f"Agent tool {plan.tool_name} completed without a result.",
                stage="tool",
                fallback_reason="missing_tool_result",
            )

        evidence: list[AgentEvidenceItem] = []
        citations: list[AgentCitationRef] = []
        if tool_result.tool_name in _GROUNDED_RETRIEVAL_TOOLS:
            evidence, citations = self._retrieval_grounding(tool_result.data)

        if tool_result.effect == "write" or skip_synthesis:
            return ProductAgentRunResult(
                status="completed",
                plan=plan,
                output_text=tool_result.output_text,
                provider=tool_result.provider,
                model=tool_result.model,
                request_id=request_id,
                tool_result=tool_result,
                route=route,
                evidence=tuple(evidence),
                citations=tuple(citations),
            )

        if tool_result.tool_name in _GROUNDED_RETRIEVAL_TOOLS:
            answer = self._synthesize_grounded(
                payload=payload,
                reading=reading,
                history=history,
                request_id=request_id,
                control=control,
                event_sink=event_sink,
                evidence=evidence,
                citations=citations,
            )
            return ProductAgentRunResult(
                status="completed",
                plan=plan,
                output_text=answer.output_text,
                provider=answer.provider,
                model=answer.model,
                request_id=answer.request_id,
                tool_result=tool_result,
                route=route,
                evidence=tuple(evidence),
                citations=tuple(citations),
            )

        observation = json.dumps(
            {
                "tool_name": tool_result.tool_name,
                "output_text": tool_result.output_text,
                "data": tool_result.data or {},
            },
            ensure_ascii=False,
        )
        answer = self._synthesize(
            payload=payload,
            reading=reading,
            history=history,
            request_id=request_id,
            control=control,
            event_sink=event_sink,
            tool_name=tool_result.tool_name,
            tool_context=observation,
        )
        return ProductAgentRunResult(
            status="completed",
            plan=plan,
            output_text=answer.output_text,
            provider=answer.provider,
            model=answer.model,
            request_id=answer.request_id,
            tool_result=tool_result,
            route=route,
        )

    def close(self) -> None:
        router_close = getattr(self._semantic_router, "close", None)
        if callable(router_close):
            router_close()
        planner_close = getattr(self._multi_step_planner, "close", None)
        if callable(planner_close):
            planner_close()
        chat_close = getattr(self._chat_service, "close", None)
        if callable(chat_close):
            chat_close()
