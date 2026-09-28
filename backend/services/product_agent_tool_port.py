"""Worker-facing Tool boundary backed by the existing product Agent services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.agent_core.orchestration.agent_registry import AgentRegistry
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import ScopeContext, TaskSpec
from backend.services.agent_tool_registry import (
    AgentToolExecutionResult,
    AgentToolRegistry,
)
from backend.services.product_agent_service import ProductAgentService

TaskResolver = Callable[[str, str], TaskSpec | None]
ScopeResolver = Callable[[str, str, str], ScopeContext | None]
ToolContextProvider = Callable[[TaskSpec, ScopeContext], Mapping[str, Any]]
ToolEventSink = Callable[[str, dict[str, Any]], None]
WriteConfirmationProvider = Callable[[str, str, str], bool]

_SERVER_OWNED_ARGUMENTS = frozenset(
    {
        "agent_id",
        "confirmed_write_tools",
        "enabled_tools",
        "filesystem_workspace_id",
        "knowledge_document_ids",
        "knowledge_scope_allow_global",
        "request_id",
        "research_source_ids",
        "run_id",
        "scope_ref",
        "step_id",
        "task_id",
        "tool_call_id",
        "trace_id",
        "workspace_id",
    }
)


class ProductAgentToolRuntimePort:
    """Authorize a worker invocation, then delegate it to ProductAgentService."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: AgentToolRegistry,
        product_agent_service: ProductAgentService,
        task_resolver: TaskResolver,
        scope_resolver: ScopeResolver,
        context_provider: ToolContextProvider,
        write_confirmation_provider: WriteConfirmationProvider | None = None,
    ) -> None:
        self._agents = agent_registry
        self._tools = tool_registry
        self._product_agent = product_agent_service
        self._resolve_task = task_resolver
        self._resolve_scope = scope_resolver
        self._context_for_tool = context_provider
        self._write_confirmation = write_confirmation_provider or (
            lambda _run_id, _task_id, _tool_name: False
        )

    def execute(
        self,
        *,
        run_id: str,
        task_id: str,
        agent_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        scope_ref: str,
        control: AgentRunControl | None = None,
        event_sink: ToolEventSink | None = None,
    ) -> AgentToolExecutionResult:
        run = str(run_id or "").strip()
        task_key = str(task_id or "").strip()
        agent_key = str(agent_id or "").strip()
        name = str(tool_name or "").strip()
        requested_scope = str(scope_ref or "").strip()
        if not all((run, task_key, agent_key, name, requested_scope)):
            raise ValueError("run, task, agent, tool, and scope identifiers are required")

        task = self._resolve_task(run, task_key)
        if task is None or task.task_id != task_key:
            raise PermissionError("authoritative task is unavailable")
        try:
            task_agent_id = task.agent_id
        except (KeyError, ValueError) as exc:
            raise PermissionError("task Agent is not registered") from exc
        if task_agent_id != agent_key:
            raise PermissionError("task Agent does not match the requested agent")
        if task.scope_ref != requested_scope:
            raise PermissionError("task scope does not match the requested scope")
        if name not in task.allowed_tools:
            raise PermissionError(f"task is not allowed to use tool {name}")
        try:
            self._agents.authorize_tool(agent_key, name)
        except (KeyError, ValueError) as exc:
            raise PermissionError(str(exc)) from exc

        scope = self._resolve_scope(run, task_key, requested_scope)
        if scope is None or scope.scope_ref != requested_scope:
            raise PermissionError("authoritative scope is unavailable or does not match")

        definition = self._tools.get_definition(name)
        if definition is None:
            raise PermissionError(f"agent tool {name} is not registered on the server")
        try:
            validated_arguments = self._tools.validate_planner_arguments(
                name, dict(arguments or {})
            )
            definition.parse_args(validated_arguments)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid arguments for agent tool {name}: {exc}") from exc
        conflicting_arguments = _SERVER_OWNED_ARGUMENTS.intersection(
            validated_arguments
        )
        if conflicting_arguments:
            raise ValueError(
                "agent tool arguments cannot override server context: "
                f"{sorted(conflicting_arguments)}"
            )

        context = dict(self._context_for_tool(task, scope))
        for reserved in ("control", "event_sink", "_resolved_route", "_skip_synthesis"):
            context.pop(reserved, None)
        context.setdefault("source_text", "")
        context.setdefault("request_id", 0)
        context.update(validated_arguments)
        context["run_id"] = run
        context["workspace_id"] = scope.workspace_id
        context["knowledge_document_ids"] = list(scope.allowed_document_ids)
        context["knowledge_scope_allow_global"] = scope.mode.value == "unscoped_global"
        context["research_source_ids"] = sorted(
            {*scope.allowed_note_ids, *scope.allowed_item_ids}
        )
        context["enabled_tools"] = [name]
        context["step_id"] = f"{task_key}:{name}"
        confirmed = (
            definition.spec.requires_confirmation
            and self._write_confirmation(run, task_key, name)
        )
        context["confirmed_write_tools"] = [name] if confirmed else []
        route = AgentRouteDecision(
            kind="tool",
            source="planner",
            intent="specialist_tool",
            tool_name=name,
            user_visible_reason="Authorized specialist Tool invocation.",
            arguments=validated_arguments,
        )

        def forward_event(event_type: str, payload: dict[str, Any]) -> None:
            if event_sink is not None:
                event_sink(
                    event_type,
                    {
                        **payload,
                        "run_id": run,
                        "task_id": task_key,
                        "agent_id": agent_key,
                    },
                )

        result = self._product_agent.run(
            control=control or AgentRunControl(),
            event_sink=forward_event if event_sink is not None else None,
            _resolved_route=route,
            _skip_synthesis=True,
            **context,
        )
        if result.status == "confirmation_required":
            raise PermissionError(
                f"agent tool {name} requires one-time write confirmation"
            )
        if result.tool_result is None:
            raise RuntimeError(f"agent tool {name} completed without a typed result")
        return result.tool_result


__all__ = ["ProductAgentToolRuntimePort"]
