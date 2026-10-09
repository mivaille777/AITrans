from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from langgraph.types import interrupt

from app.ai.knowledge_context import normalize_knowledge_context
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentRuntimeError,
    AgentToolError,
    AgentToolTimeoutError,
)
from backend.agent_core.reliability import (
    AgentRunControl,
    is_transient_provider_error,
    run_safe_tool_with_timeout,
)
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
from backend.services.agent_tool_execution_service import AgentToolExecutionService
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
        "read_knowledge_chunk",
        "read_knowledge_section",
        "search_research_notes",
        "search_research_memory",
        "analyze_cross_document_research",
        "search_evidence_ledger",
    }
)
_KNOWLEDGE_READ_TOOLS = frozenset(
    {"read_knowledge_chunk", "read_knowledge_section"}
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
            AgentCancelledError,
            AgentBudgetExceededError,
            ValueError,
            PermissionError,
        ),
    ):
        return False
    # AgentToolTimeoutError is the hard outer deadline for a worker that may
    # still be running. Retrying it can overlap the original operation; provider
    # timeouts raised by the provider remain retryable through the classifier.
    return is_transient_provider_error(exc)


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
        function_calling_enabled: bool = False,
    ) -> None:
        self._registry = registry
        self.function_calling_enabled = bool(function_calling_enabled)
        self._chat_service = chat_service
        self._router = router or AgentDeterministicRouterService()
        self._semantic_router = (
            semantic_router or planner or AgentSemanticRouterService()
        )
        self._multi_step_planner = multi_step_planner or AgentMultiStepPlannerService()
        self._grounded_synthesis_service = (
            grounded_synthesis_service
            or GroundedSynthesisService(chat_service=chat_service)
        )

    @property
    def tool_registry(self) -> AgentToolRegistry:
        """Expose the server-owned typed registry for orchestration validation."""

        return self._registry

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
            "knowledge_context": normalize_knowledge_context(
                payload.get("knowledge_context")
            ),
            "filesystem_workspace_files": payload.get(
                "filesystem_workspace_files", []
            ),
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

    def _primitive_tool_name(self, name: str) -> str:
        resolve = getattr(self._registry, "primitive_name", None)
        return resolve(name) if callable(resolve) else name

    def _tools_for_payload(self, payload: dict[str, Any]):
        """Return the catalog allowed for this run.

        An empty list intentionally means automatic mode and preserves the
        existing catalog. A non-empty list is a hard boundary shared by route
        selection, planning, and execution.
        """
        selected = _trusted_scope_ids(payload.get("enabled_tools", ()), limit=64)
        blocked = set(
            _trusted_scope_ids(payload.get("disabled_tools", ()), limit=64)
        )
        tools = tuple(
            tool
            for tool in self._registry.list_tools()
            if str(getattr(tool, "name", "") or "") not in blocked
            and (str(getattr(tool, "name", "") or "") != "read_workspace_file" or payload.get("filesystem_workspace_id"))
        )
        if not selected:
            availability = getattr(self._registry, "availability", None)
            if callable(availability):
                tools = tuple(tool for tool in tools if availability(tool.name, payload=payload)[0])
            from backend.services.tool_capability_router import filter_capabilities
            return filter_capabilities(tools, payload.get("user_message", ""), primitive_name=self._primitive_tool_name)

        available = {str(getattr(tool, "name", "") or "") for tool in tools}
        unknown = sorted(set(selected) - available)
        if unknown:
            raise AgentRuntimeError(
                f"Unknown enabled Agent tool(s): {', '.join(unknown)}",
                stage="planner",
                fallback_reason="invalid_enabled_tools",
            )
        selected_set = set(selected)
        return tuple(tool for tool in tools if str(getattr(tool, "name", "") or "") in selected_set)

    @property
    def jit_search_read_enabled(self) -> bool:
        return bool(getattr(self._registry, "jit_search_read_enabled", True))

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
            "knowledge_context": dict(reading.get("knowledge_context", {}) or {}),
            "filesystem_workspace_files": reading.get(
                "filesystem_workspace_files", []
            ),
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
            tools=self._tools_for_payload(payload),
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
            tools=self._tools_for_payload(payload),
            **({"allow_simple_plan": True} if payload.get("execution_mode") == "plan_execute" else {}),
            max_steps=min(
                active_control.policy.max_plan_steps,
                active_control.policy.max_tool_calls,
            ),
            user_message=str(payload["user_message"]),
            history=history,
            **reading,
        )
        active_control.checkpoint("multi_step_planner_result")
        if payload.get("execution_mode") == "plan_execute" and getattr(self._registry, "workspace_files", None):
            from backend.agent_tools.workspace_files import OPERATIONS
            from backend.services.workspace_file_service import WorkspaceFileError, digest
            service = self._registry.workspace_files
            workspace_id = payload.get("filesystem_workspace_id", "")
            for step in plan.steps:
                primitive = self._primitive_tool_name(step.tool_name)
                if primitive not in OPERATIONS:
                    continue
                file_arguments = self._registry.workspace_file_arguments(step.tool_name, step.arguments)
                if primitive in {"edit_workspace_file", "write_workspace_file"} and not file_arguments.get("expected_sha256"):
                    version = service.read(workspace_id, file_arguments["relative_path"], max_lines=1)["sha256"]
                    if "expected_sha256" not in self._registry.get_tool(step.tool_name).input_schema:
                        raise ValueError("文件工具预设必须允许绑定当前文件版本。")
                    step.arguments["expected_sha256"] = version
                    file_arguments["expected_sha256"] = version
                try:
                    step.file_preview = service.preview(workspace_id, OPERATIONS[primitive], file_arguments)
                except WorkspaceFileError as exc:
                    if exc.code != "parent_missing" or primitive not in {"create_workspace_file", "create_workspace_directory"}:
                        raise
                    # A preceding directory creation can satisfy this dependency.
                    parent = file_arguments["relative_path"].replace("\\", "/").rsplit("/", 1)[0]
                    if not any(item.tool_name == "create_workspace_directory" and item.arguments.get("relative_path") == parent for item in plan.steps[:plan.steps.index(step)]):
                        raise
                    content = file_arguments.get("content", "")
                    step.file_preview = {"relative_path": file_arguments["relative_path"], "operation": OPERATIONS[primitive],
                                         "size_before": 0, "size_after": len(content.encode("utf-8")), "diff": content,
                                         "diff_truncated": False, "before_sha256": "",
                                         "after_sha256": digest(content.encode("utf-8")) if primitive == "create_workspace_file" else "", "change_id": ""}
        return plan, {
            "duration_ms": _duration_ms(started),
            "provider": str(
                getattr(self._multi_step_planner, "provider_name", "") or ""
            ),
            "model": str(getattr(self._multi_step_planner, "model", "") or ""),
            "prompt_id": str(getattr(self._multi_step_planner, "prompt_id", "") or ""),
            "llm_called": True,
        }

    def _validated_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        validate = getattr(self._registry, "validate_planner_arguments", None)
        if callable(validate):
            return validate(tool_name, arguments)
        return {str(key): str(value) for key, value in dict(arguments or {}).items()}

    def _allows_safe_retry(self, tool_name: str, *, effect: str) -> bool:
        allows = getattr(self._registry, "allows_safe_retry", None)
        if callable(allows):
            return bool(allows(tool_name))
        return effect != "write"

    def _trace_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        sanitize = getattr(self._registry, "trace_arguments", None)
        if callable(sanitize):
            return sanitize(tool_name, arguments)
        return dict(arguments or {})

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
        durable_write_interrupt: bool = False,
    ) -> tuple[AgentToolExecutionResult | None, bool]:
        selected = set(_trusted_scope_ids(payload.get("enabled_tools", ()), limit=64))
        if selected and plan.tool_name not in selected:
            raise AgentToolError(
                f"Agent tool {plan.tool_name} is outside the enabled tool scope.",
                stage="tool",
                fallback_reason="tool_outside_enabled_scope",
            )
        spec = self._registry.get_tool(plan.tool_name)
        if spec is None:
            raise RuntimeError(
                f"Validated route references missing tool: {plan.tool_name}"
            )

        call_event = {
            "name": spec.name,
            "arguments": self._trace_arguments(spec.name, plan.arguments),
            "effect": spec.effect,
            "requires_confirmation": spec.requires_confirmation,
            "route_source": route.source,
            "request_id": request_id,
            "step_id": str(payload.get("step_id", "direct") or "direct"),
        }
        from backend.services.workspace_file_service import FILE_TOOLS
        if self._primitive_tool_name(spec.name) in FILE_TOOLS and payload.get("chat_configuration"):
            # Recheck the live session on every call, including checkpoint
            # resumes: the saved state cannot grant revoked write access.
            from backend.api.chat_sessions import get_chat_session_service
            live = get_chat_session_service().get(str(payload.get("session_id", "")))
            if live.filesystem_workspace_id != payload.get("filesystem_workspace_id", ""):
                raise AgentToolError("工作区已变化，请重新发起任务。", stage="tool", fallback_reason="workspace_changed")
            payload = {**payload, "filesystem_access": live.filesystem_access}
        availability = getattr(self._registry, "availability", None)
        if callable(availability):
            available, reason = availability(spec.name, payload={**reading, **payload})
            if not available:
                raise AgentToolError(reason, stage="tool", fallback_reason="tool_unavailable")
        get_definition = getattr(self._registry, "get_definition", None)
        typed = callable(get_definition) and get_definition(spec.name) is not None

        confirmed = {
            str(item).strip()
            for item in payload.get("confirmed_write_tools", ())
            if str(item).strip()
        }
        try:
            validated_arguments = self._validated_arguments(spec.name, plan.arguments)
        except (KeyError, ValueError) as exc:
            raise AgentToolError(
                f"Agent tool {spec.name} received invalid route arguments: {exc}",
                stage="tool",
                fallback_reason="invalid_tool_arguments",
            ) from exc

        write_confirmed = spec.name in confirmed
        from backend.services.workspace_file_service import FILE_TOOLS, FILE_WRITE_TOOLS
        primitive = self._primitive_tool_name(spec.name)
        file_preview = None
        file_preapproved = False
        if primitive in FILE_WRITE_TOOLS:
            from backend.agent_tools.workspace_files import OPERATIONS
            from backend.services.workspace_file_intent import explicit_new_file_request
            file_service = self._registry.workspace_files
            file_arguments = self._registry.workspace_file_arguments(spec.name, validated_arguments)
            file_preview = file_service.preview(payload.get("filesystem_workspace_id", ""), OPERATIONS[primitive], file_arguments)
            # This exemption is narrow: an explicit new path in the current
            # request, a writable session, and exclusive creation semantics.
            if (primitive == "create_workspace_file" and payload.get("execution_mode") != "plan_execute"
                    and explicit_new_file_request(payload.get("user_message", ""), file_arguments["relative_path"])):
                write_confirmed = True
                file_preapproved = True
            approved = payload.get("approved_file_steps", [])
            from backend.services.workspace_file_service import preview_fingerprint
            if any(item == {"tool_name": spec.name, "arguments": validated_arguments,
                            "workspace_id": payload.get("filesystem_workspace_id", ""),
                            "file_preview_hash": preview_fingerprint(file_preview)}
                   for item in approved):
                write_confirmed = True
                file_preapproved = True
        if spec.effect == "write" and spec.requires_confirmation and not file_preapproved:
            if durable_write_interrupt:
                normalized = json.dumps(
                    validated_arguments,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                arguments_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                step_id = str(payload.get("step_id", "direct") or "direct")
                run_id = str(payload.get("run_id", "") or "")
                tool_version = str(getattr(spec, "tool_version", "1") or "1")
                call_material = json.dumps(
                    (run_id, step_id, spec.name, arguments_hash, tool_version),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                intent_id = hashlib.sha256(call_material.encode("utf-8")).hexdigest()
                intent = {
                    "intent_id": intent_id,
                    "run_id": run_id,
                    "task_id": str(payload.get("task_id", "") or ""),
                    "step_id": step_id,
                    "tool_name": spec.name,
                    "tool_version": tool_version,
                    "arguments_hash": arguments_hash,
                    # The target is included in the full canonical argument
                    # fingerprint. Keep only the fingerprint in the event log.
                    "target_hash": arguments_hash,
                }
                if file_preview is not None:
                    intent["file_preview"] = file_preview
                raw_decision = payload.get("write_confirmation_decision", {})
                has_decision = isinstance(raw_decision, dict) and bool(raw_decision)
                if not has_decision:
                    self._emit(
                        event_sink,
                        "write_confirmation_required",
                        {"intent": intent},
                    )
                decision = interrupt(intent)
                if not isinstance(decision, dict) or any(
                    decision.get(key) != value for key, value in intent.items()
                ):
                    raise AgentToolError(
                        "The write authorization does not match the pending tool arguments.",
                        stage="tool",
                        fallback_reason="write_confirmation_mismatch",
                    )
                if decision.get("approved") is not True:
                    raise AgentCancelledError("The write action was rejected by the user.")
                write_confirmed = True
            elif not write_confirmed:
                self._emit(event_sink, "tool_call", call_event)
                return None, True

        execution_payload = {
            **reading,
            "style": str(payload.get("style", "academic") or "academic"),
            "conversation_id": str(payload.get("conversation_id", "") or ""),
            "request_id": request_id,
            **validated_arguments,
        }
        if spec.name in {"translate_selection", "polish_selection"}:
            preferences = payload.get("memory_language_preferences", [])
            if isinstance(preferences, list):
                execution_payload["memory_preferences"] = [
                    dict(item) for item in preferences[:32] if isinstance(item, dict)
                ]
        # Knowledge/Canvas context is prompt context for planning and synthesis,
        # not an implicit argument to registered product tools.
        execution_payload.pop("knowledge_context", None)
        if spec.name == "export_markdown_document":
            export_arguments = payload.get("markdown_export_arguments")
            if export_arguments:
                execution_payload.update(export_arguments)
            previous_answer = next((str(item[1]) for item in reversed(payload.get("history", ())) if len(item) >= 2 and item[0] == "assistant"), "")
            execution_payload["ai_content"] = str(payload.get("ai_content", "") or previous_answer)[:50_000]
        workspace_id = str(payload.get("workspace_id", "") or "").strip()
        if workspace_id:
            execution_payload["workspace_id"] = workspace_id
        if primitive in FILE_TOOLS | {"python_execute", "read_workspace_file"}:
            execution_payload["filesystem_workspace_id"] = str(
                payload.get("filesystem_workspace_id", "") or ""
            ).strip()
            execution_payload["run_id"] = str(payload.get("run_id", "") or "").strip()
            execution_payload["trace_id"] = str(payload.get("trace_id", "") or "").strip()
            execution_payload["filesystem_access"] = payload.get("filesystem_access", "read_only")
            execution_payload["session_id"] = str(payload.get("session_id", ""))
        if self._primitive_tool_name(spec.name) in {
            "search_knowledge_base",
            "read_knowledge_chunk",
            "read_knowledge_section",
            "list_knowledge_documents",
        }:
            trusted_document_ids = _trusted_scope_ids(
                payload.get("knowledge_document_ids", ())
            )
            execution_payload["knowledge_document_ids"] = trusted_document_ids
            execution_payload["knowledge_scope_allow_global"] = bool(
                payload.get("knowledge_scope_allow_global", False)
            )
            execution_payload["trace_id"] = str(payload.get("trace_id", "") or "").strip()
            execution_payload["run_id"] = str(payload.get("run_id", "") or "").strip()
        if spec.name == "search_knowledge_base":
            trusted_document_ids = _trusted_scope_ids(
                payload.get("knowledge_document_ids", ())
            )
            if trusted_document_ids and not validated_arguments.get("document_ids") and not validated_arguments.get("document_scope"):
                execution_payload["document_ids"] = trusted_document_ids
                execution_payload["document_scope"] = ""
        elif spec.name == "search_research_notes":
            trusted_source_ids = _trusted_scope_ids(
                payload.get("research_source_ids", ())
            )
            if trusted_source_ids:
                execution_payload["source_ids"] = trusted_source_ids

        control.claim_knowledge_action(self._primitive_tool_name(spec.name))
        tool_started = monotonic()
        if typed:
            call_id = ""

            def remember_call(value: str) -> None:
                nonlocal call_id
                call_id = value
                self._emit(event_sink, "tool_call", {
                    **call_event, "tool_call_id": value,
                })

            def emit_retry(attempt: int, maximum: int, error: Exception, tool_call_id: str) -> None:
                self._emit(event_sink, "retry", {
                    "tool_name": spec.name, "attempt": attempt,
                    "max_attempts": maximum,
                    "reason": str(error) or type(error).__name__,
                    "request_id": request_id,
                    "tool_call_id": tool_call_id,
                    "step_id": str(payload.get("step_id", "direct") or "direct"),
                })

            try:
                tool_result = AgentToolExecutionService(self._registry).execute(
                    spec.name, execution_payload, control=control,
                    run_id=str(payload.get("run_id", "") or ""),
                    step_id=str(payload.get("step_id", "direct") or "direct"),
                    emit_retry=emit_retry, on_call=remember_call,
                    write_confirmed=write_confirmed,
                )
            except Exception as exc:
                self._emit(event_sink, "failure", {
                    "stage": "tool", "tool_name": spec.name,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:2000],
                    "error_code": str(getattr(exc, "fallback_reason", "") or "tool_execution_failed"),
                    "execution_outcome": "unknown" if spec.effect == "write" or isinstance(exc, AgentToolTimeoutError) else "failed",
                    "tool_call_id": call_id,
                    "step_id": str(payload.get("step_id", "direct") or "direct"),
                })
                raise
        elif spec.effect == "write":
            self._emit(event_sink, "tool_call", call_event)
            control.checkpoint(f"write_tool:{spec.name}")
            tool_result = self._registry.execute(spec.name, **execution_payload)
        elif not self._allows_safe_retry(spec.name, effect=spec.effect):
            self._emit(event_sink, "tool_call", call_event)
            control.checkpoint(f"tool:{spec.name}")
            tool_result = self._registry.execute(spec.name, **execution_payload)
        else:
            self._emit(event_sink, "tool_call", call_event)
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

        if not typed:
            tool_result = AgentToolExecutionService(self._registry)._verify(spec.name, execution_payload, tool_result, control)

        if self._primitive_tool_name(tool_result.tool_name) == "search_knowledge_base":
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
            if self._primitive_tool_name(tool_result.tool_name) in _GROUNDED_RETRIEVAL_TOOLS
            else tool_result.data or {}
        )
        result_data = tool_result.data if isinstance(tool_result.data, dict) else {}
        trace_output_text = tool_result.output_text
        if tool_result.tool_name == "python_execute":
            output_files = result_data.get("output_files", ())
            trace_data = {
                key: result_data[key]
                for key in (
                    "sandbox_id",
                    "runtime",
                    "image",
                    "status",
                    "duration_ms",
                    "exit_code",
                    "timed_out",
                    "output_limit_exceeded",
                    "oom_killed",
                    "stdout_bytes",
                    "stderr_bytes",
                )
                if key in result_data
            }
            trace_data["output_file_count"] = (
                len(output_files) if isinstance(output_files, (list, tuple)) else 0
            )
            # The bounded stdout/stderr are returned to synthesis, but trace
            # storage only receives byte counts and execution metadata.
            trace_output_text = ""
        tool_metrics: dict[str, int] = {}
        if self._primitive_tool_name(tool_result.tool_name) == "search_knowledge_base":
            results = result_data.get("results", ())
            tool_metrics["candidate_count"] = (
                len(results) if isinstance(results, (list, tuple)) else 0
            )
        elif tool_result.tool_name in _KNOWLEDGE_READ_TOOLS:
            chunks = result_data.get("chunks", ())
            tool_metrics["candidate_count"] = (
                len(chunks) if isinstance(chunks, (list, tuple)) else 0
            )
        self._emit(
            event_sink,
            "tool_result",
            {
                "tool_name": tool_result.tool_name,
                "output_text": trace_output_text,
                "output_chars": len(tool_result.output_text),
                **tool_metrics,
                "effect": tool_result.effect,
                "provider": tool_result.provider,
                "model": tool_result.model,
                "request_id": tool_result.request_id,
                "data": trace_data,
                "duration_ms": _duration_ms(tool_started),
                "status": tool_result.status,
                "verification": tool_result.verification,
                "attempt": tool_result.attempt,
                "error_code": tool_result.error_code,
                "tool_call_id": call_id if typed else "",
                "step_id": str(payload.get("step_id", "direct") or "direct"),
            },
        )
        self._emit(event_sink, "tool_verification", {
            "tool_name": tool_result.tool_name, "tool_call_id": tool_result.tool_call_id,
            "step_id": str(payload.get("step_id", "direct") or "direct"),
            **tool_result.verification,
        })
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
            **({"knowledge_access_policy": "never"} if self.function_calling_enabled else {}),
            **({"skill_session": control.skill_session} if control.skill_session is not None else {}),
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
        if self.function_calling_enabled:
            kwargs["knowledge_access_policy"] = "never"
            if control.skill_session is not None:
                kwargs["skill_session"] = control.skill_session
        if tool_name:
            kwargs["tool_name"] = tool_name
            kwargs["tool_context"] = tool_context
            from backend.services.script_plot_intent import wants_plot_execution
            if wants_plot_execution(str(payload["user_message"])):
                kwargs["tool_context"] += (
                    "\nDelivery instructions: the chat already displays the actual image, "
                    "original source, downloads and execution logs from these receipts. "
                    "Briefly summarize actual success/failure and refer to 查看代码／下载脚本. "
                    "Do not regenerate or present a different script as the executed source; "
                    "do not invent Markdown image URLs, download links, GUI instructions or files."
                )
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
                        "tool_name": str(
                            item.get("tool_name", "") or item.get("name", "") or ""
                        ),
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
            if self._primitive_tool_name(str(item.get("tool_name", "") or item.get("name", "") or ""))
            in _GROUNDED_RETRIEVAL_TOOLS
        ]
        evidence: list[AgentEvidenceItem] = []
        citations: list[AgentCitationRef] = []
        if grounded_results:
            seen_evidence: set[str] = set()
            for item in grounded_results:
                if self.jit_search_read_enabled and self._primitive_tool_name(str(
                    item.get("tool_name", "") or item.get("name", "") or ""
                )) == "search_knowledge_base":
                    continue
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
        durable_write_interrupt = bool(payload.pop("_durable_write_interrupt", False))
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
                    "arguments": self._trace_arguments(plan.tool_name, plan.arguments),
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
            durable_write_interrupt=durable_write_interrupt,
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
        if (
            self._primitive_tool_name(tool_result.tool_name) in _GROUNDED_RETRIEVAL_TOOLS
            and (
                self._primitive_tool_name(tool_result.tool_name) != "search_knowledge_base"
                or not self.jit_search_read_enabled
            )
        ):
            evidence, citations = self._retrieval_grounding(tool_result.data)

        if tool_result.effect == "write" or skip_synthesis or tool_result.tool_name == "export_markdown_document":
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

        if self._primitive_tool_name(tool_result.tool_name) in _GROUNDED_RETRIEVAL_TOOLS:
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
