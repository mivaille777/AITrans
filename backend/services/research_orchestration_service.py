from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.agent_core.exceptions import AgentRuntimeError
from backend.agent_core.multi_agent.trace import (
    MultiAgentTraceCollector,
    MultiAgentTraceEvent,
)
from backend.agent_core.orchestration.memory import NullMemoryPort
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.agent_core.orchestration.scope_resolver import AuthoritativeScopeResolver
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import (
    ScopeContext,
    ScopeKind,
    TaskResult,
    ValidatedTaskPlan,
)


@dataclass(frozen=True, slots=True)
class ResearchOrchestrationRun:
    run_id: str
    trace_id: str
    route: OrchestrationRoute
    scope: ScopeContext
    memory_snapshot: dict[str, Any]
    task_plan: ValidatedTaskPlan | None
    results: tuple[TaskResult, ...]
    outputs: dict[str, Any]
    events: tuple[MultiAgentTraceEvent, ...]
    total_duration_ms: int
    direct_output: Any = None
    direct_delivery: bool = False

    @property
    def plan(self) -> tuple[dict[str, Any], ...]:
        if self.task_plan is None:
            return ()
        return tuple(
            {
                "task_id": task.task_id,
                "agent": task.role.value,
                "task": task.objective,
                "depends_on": list(task.depends_on),
            }
            for task in self.task_plan.tasks
        )


class ResearchOrchestrationService:
    def __init__(
        self,
        *,
        scope_resolver: AuthoritativeScopeResolver,
        executor: Any,
        router: ResearchTaskRouter | None = None,
        planner: ValidatedSupervisorPlanner | None = None,
        memory_port: Any | None = None,
        temporary_executor: Any | None = None,
    ) -> None:
        self.scope_resolver = scope_resolver
        self.executor = executor
        self.router = router or ResearchTaskRouter()
        self.planner = planner or ValidatedSupervisorPlanner()
        self.memory_port = memory_port or NullMemoryPort()
        self.temporary_executor = temporary_executor

    @staticmethod
    def _scope_request(runtime_context: dict[str, Any]) -> tuple[ScopeKind, str]:
        workspace_id = str(runtime_context.get("workspace_id", "") or "").strip()
        board_id = str(runtime_context.get("knowledge_board_id", "") or "").strip()
        collection_id = str(
            runtime_context.get("knowledge_collection_id", "") or ""
        ).strip()
        if workspace_id:
            return ScopeKind.RESEARCH_WORKSPACE, workspace_id
        if board_id:
            return ScopeKind.KNOWLEDGE_BOARD, board_id
        if collection_id:
            return ScopeKind.KNOWLEDGE_COLLECTION, collection_id
        if any(
            runtime_context.get(key)
            for key in (
                "knowledge_document_ids",
                "research_note_ids",
                "knowledge_item_ids",
            )
        ):
            return ScopeKind.EXPLICIT_SELECTION, ""
        return ScopeKind.GLOBAL, ""

    def route(
        self,
        user_input: str,
        runtime_context: dict[str, Any] | None = None,
        *,
        mode: str = "auto",
    ) -> OrchestrationRoute:
        return self.router.route(user_input, runtime_context, mode=mode)

    def resolve_memory(
        self,
        *,
        profile_id: str,
        run_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> tuple[ScopeContext, dict[str, Any]]:
        context = dict(runtime_context or {})
        kind, scope_id = self._scope_request(context)
        scope = self.scope_resolver.resolve(
            profile_id=profile_id,
            scope_kind=kind,
            scope_id=scope_id,
            selected_document_ids=context.get("knowledge_document_ids", ()) or (),
            selected_note_ids=context.get("research_note_ids", ()) or (),
            selected_item_ids=context.get("knowledge_item_ids", ()) or (),
            explicit_current_source_refs=context.get("research_source_ids", ()) or (),
        )
        temporary = bool(context.get("temporary", False))
        load_snapshot = self.memory_port.load_snapshot
        memory_arguments: dict[str, Any] = {
            "profile_id": profile_id,
            "scope": scope,
        }
        parameters = inspect.signature(load_snapshot).parameters
        if "run_id" in parameters:
            memory_arguments["run_id"] = run_id
        if "temporary" in parameters:
            memory_arguments["temporary"] = temporary
        memory_snapshot = dict(load_snapshot(**memory_arguments))
        if memory_snapshot.get("status") == "invalidated":
            raise AgentRuntimeError(
                "The frozen memory snapshot was invalidated by deletion or scope change.",
                stage="memory",
                fallback_reason="memory_snapshot_invalidated",
            )
        return scope, memory_snapshot

    def run(
        self,
        user_input: str,
        *,
        profile_id: str,
        mode: str = "auto",
        run_id: str | None = None,
        trace_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
        event_sink: Callable[[MultiAgentTraceEvent], None] | None = None,
        control: AgentRunControl | None = None,
    ) -> ResearchOrchestrationRun:
        context = dict(runtime_context or {})
        route = self.route(user_input, context, mode=mode)
        collector = MultiAgentTraceCollector(
            run_id=run_id,
            trace_id=trace_id,
            event_sink=event_sink,
        )
        temporary = bool(context.get("temporary", False))
        scope, memory_snapshot = self.resolve_memory(
            profile_id=profile_id,
            run_id=collector.run_id,
            runtime_context=context,
        )
        collector.emit(
            "supervisor_started",
            actor="supervisor",
            status="running",
            payload={"lane": route.lane.value, "scope_ref": scope.scope_ref},
        )
        task_plan = self.planner.plan(route=route, objective=user_input, scope=scope)
        collector.emit(
            "supervisor_planned",
            actor="supervisor",
            status="complete",
            payload={
                "lane": route.lane.value,
                "task_count": len(task_plan.tasks) if task_plan else 0,
                "agents": [task.role.value for task in task_plan.tasks]
                if task_plan
                else [],
            },
        )
        if task_plan is not None:
            if task_plan.plan_revision > 1:
                collector.emit(
                    "plan_revised",
                    actor="supervisor",
                    status="complete",
                    payload={
                        "plan_revision": task_plan.plan_revision,
                        "reason_code": "validated_repair_or_evidence_supplement",
                    },
                )
            for task in task_plan.tasks:
                collector.emit(
                    "task_planned",
                    actor=task.role.value,
                    status="pending",
                    payload={
                        "task_id": task.task_id,
                        "parent_task_id": "",
                        "attempt": 0,
                        "plan_revision": task.plan_revision,
                        "reason_code": "",
                        "usage": {},
                    },
                )
        if route.lane is OrchestrationLane.FAST or task_plan is None:
            execution_results: tuple[TaskResult, ...] = ()
            outputs: dict[str, Any] = {}
            direct_output = None
            direct_delivery = False
        else:
            active_executor = (
                self.temporary_executor
                if temporary and self.temporary_executor is not None
                else self.executor
            )
            execution = active_executor.execute(
                plan=task_plan,
                scope=scope,
                memory_snapshot=memory_snapshot,
                run_id=collector.run_id,
                collector=collector,
                control=control,
            )
            execution_results = execution.results
            outputs = execution.outputs
            direct_output = execution.direct_output
            direct_delivery = execution.direct_delivery
            for result in execution_results:
                collector.emit(
                    "agent_completed"
                    if result.status.value in {"succeeded", "partial"}
                    else "agent_failed",
                    actor=task_plan.task_map()[result.task_id].role.value,
                    status=result.status.value,
                    payload={
                        "task_id": result.task_id,
                        "error_code": result.error_code,
                    },
                )
            submit_candidates = getattr(self.memory_port, "submit_candidates", None)
            if callable(submit_candidates):
                candidate_arguments: dict[str, Any] = {
                    "profile_id": profile_id,
                    "workspace_id": scope.workspace_id,
                    "artifact_refs": [
                        ref
                        for result in execution_results
                        for ref in result.artifact_refs
                    ],
                    "temporary": temporary,
                }
                if "scope_ref" in inspect.signature(submit_candidates).parameters:
                    candidate_arguments["scope_ref"] = scope.scope_ref
                submit_candidates(
                    **candidate_arguments,
                )
        partial = any(
            item.status.value not in {"succeeded", "skipped"}
            for item in execution_results
        )
        if partial:
            collector.emit(
                "workflow_partial",
                actor="supervisor",
                status="partial",
                payload={
                    "reason_code": "one_or_more_tasks_incomplete",
                    "task_count": len(execution_results),
                },
            )
        collector.emit(
            "workflow_completed",
            actor="supervisor",
            status="complete",
            payload={"completed_task_count": len(execution_results)},
        )
        return ResearchOrchestrationRun(
            run_id=collector.run_id,
            trace_id=collector.trace_id,
            route=route,
            scope=scope,
            memory_snapshot=memory_snapshot,
            task_plan=task_plan,
            results=execution_results,
            outputs=outputs,
            events=collector.events,
            total_duration_ms=collector.total_duration_ms,
            direct_output=direct_output,
            direct_delivery=direct_delivery,
        )


__all__ = ["ResearchOrchestrationRun", "ResearchOrchestrationService"]
