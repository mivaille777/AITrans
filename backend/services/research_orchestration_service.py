from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agent_core.multi_agent.trace import (
    MultiAgentTraceCollector,
    MultiAgentTraceEvent,
)
from backend.agent_core.orchestration.memory import NullMemoryPort
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.orchestration.router import ResearchTaskRouter
from backend.agent_core.orchestration.scope_resolver import AuthoritativeScopeResolver
from backend.agent_core.orchestration.serial_executor import SerialTaskGraphExecutor
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
        executor: SerialTaskGraphExecutor,
        router: ResearchTaskRouter | None = None,
        planner: ValidatedSupervisorPlanner | None = None,
        memory_port: Any | None = None,
    ) -> None:
        self.scope_resolver = scope_resolver
        self.executor = executor
        self.router = router or ResearchTaskRouter()
        self.planner = planner or ValidatedSupervisorPlanner()
        self.memory_port = memory_port or NullMemoryPort()

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

    def run(
        self,
        user_input: str,
        *,
        profile_id: str,
        mode: str = "auto",
        run_id: str | None = None,
        trace_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> ResearchOrchestrationRun:
        context = dict(runtime_context or {})
        route = self.route(user_input, context, mode=mode)
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
        memory_snapshot = dict(
            self.memory_port.load_snapshot(profile_id=profile_id, scope=scope)
        )
        collector = MultiAgentTraceCollector(run_id=run_id, trace_id=trace_id)
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
                "agents": [task.role.value for task in task_plan.tasks] if task_plan else [],
            },
        )
        if route.lane is OrchestrationLane.FAST or task_plan is None:
            execution_results: tuple[TaskResult, ...] = ()
            outputs: dict[str, Any] = {}
            direct_output = None
            direct_delivery = False
        else:
            execution = self.executor.execute(
                plan=task_plan,
                scope=scope,
                memory_snapshot=memory_snapshot,
            )
            execution_results = execution.results
            outputs = execution.outputs
            direct_output = execution.direct_output
            direct_delivery = execution.direct_delivery
            for result in execution_results:
                collector.emit(
                    "agent_completed" if result.status.value in {"succeeded", "partial"} else "agent_failed",
                    actor=task_plan.task_map()[result.task_id].role.value,
                    status=result.status.value,
                    payload={"task_id": result.task_id, "error_code": result.error_code},
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
