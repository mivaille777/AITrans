from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
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
                "agent": task.agent_id,
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
        artifact_store: Any | None = None,
    ) -> None:
        self.scope_resolver = scope_resolver
        self.executor = executor
        self.router = router or ResearchTaskRouter()
        self.planner = planner or ValidatedSupervisorPlanner()
        self.memory_port = memory_port or NullMemoryPort()
        self.temporary_executor = temporary_executor
        self.artifact_store = artifact_store

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
        scope = self.resolve_scope(profile_id=profile_id, runtime_context=context)
        memory_snapshot = self.load_memory_snapshot(
            profile_id=profile_id,
            scope=scope,
            run_id=run_id,
            runtime_context=context,
        )
        return scope, memory_snapshot

    def memory_policy_revision(self, profile_id: str) -> str:
        reader = getattr(self.memory_port, "policy_revision", None)
        if not callable(reader):
            return ""
        return str(reader(profile_id) or "").strip()

    def resolve_scope(
        self,
        *,
        profile_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> ScopeContext:
        context = dict(runtime_context or {})
        kind, scope_id = self._scope_request(context)
        parameters = inspect.signature(self.scope_resolver.resolve).parameters
        resolve_arguments: dict[str, Any] = {
            "profile_id": profile_id,
            "scope_kind": kind,
            "scope_id": scope_id,
            "selected_document_ids": context.get("knowledge_document_ids", ()) or (),
            "selected_note_ids": context.get("research_note_ids", ()) or (),
            "selected_item_ids": context.get("knowledge_item_ids", ()) or (),
            "explicit_current_source_refs": context.get("research_source_ids", ()) or (),
        }
        accepts_policy_revision = "memory_policy_revision" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_policy_revision:
            resolve_arguments["memory_policy_revision"] = self.memory_policy_revision(
                profile_id
            )
        return self.scope_resolver.resolve(**resolve_arguments)

    def load_memory_snapshot(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        run_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = dict(runtime_context or {})
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
        if memory_snapshot.get("reason_code") == "memory_read_disabled":
            raise AgentRuntimeError(
                "The current memory policy does not allow reading this profile.",
                stage="memory",
                fallback_reason="memory_read_disabled",
            )
        snapshot_policy_revision = str(
            memory_snapshot.get("policy_revision", "") or ""
        )
        if (
            snapshot_policy_revision
            and scope.memory_policy_revision
            and snapshot_policy_revision != scope.memory_policy_revision
        ):
            raise AgentRuntimeError(
                "The memory policy changed while the snapshot was being loaded.",
                stage="memory",
                fallback_reason="memory_policy_changed",
            )
        return memory_snapshot

    def plan_tasks(
        self,
        *,
        route: OrchestrationRoute,
        objective: str,
        scope: ScopeContext,
        plan_revision: int = 1,
    ) -> ValidatedTaskPlan | None:
        return self.planner.plan(
            route=route,
            objective=objective,
            scope=scope,
            plan_revision=plan_revision,
        )

    def validate_plan(
        self,
        task_plan: ValidatedTaskPlan | None,
        *,
        scope: ScopeContext,
        require_graphs: bool = False,
    ) -> ValidatedTaskPlan | None:
        validate = getattr(self.planner, "validate", None)
        if callable(validate):
            parameters = inspect.signature(validate).parameters
            arguments: dict[str, Any] = {"scope": scope}
            if "require_graphs" in parameters:
                arguments["require_graphs"] = require_graphs
            return validate(task_plan, **arguments)
        if task_plan is None:
            return None
        from backend.agent_core.orchestration.validation import validate_task_plan

        return validate_task_plan(
            task_plan, scope=scope, require_graphs=require_graphs
        )

    def revalidate_prepared(
        self,
        *,
        profile_id: str,
        scope: ScopeContext,
        task_plan: ValidatedTaskPlan,
        run_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> tuple[ScopeContext, dict[str, Any]]:
        """Refresh authority and revocation state before a resumed executor runs."""

        fresh_scope = self.resolve_scope(
            profile_id=profile_id,
            runtime_context=runtime_context,
        )
        if fresh_scope.scope_ref != scope.scope_ref:
            raise AgentRuntimeError(
                "The prepared scope or memory policy changed before resume.",
                stage="scope",
                fallback_reason="prepared_scope_changed",
            )
        self.validate_plan(task_plan, scope=fresh_scope)
        snapshot = self.load_memory_snapshot(
            profile_id=profile_id,
            scope=fresh_scope,
            run_id=run_id,
            runtime_context=runtime_context,
        )
        return fresh_scope, snapshot

    def execute_prepared(
        self,
        *,
        route: OrchestrationRoute,
        scope: ScopeContext,
        memory_snapshot: dict[str, Any] | None,
        task_plan: ValidatedTaskPlan | None,
        profile_id: str,
        run_id: str,
        trace_id: str,
        runtime_context: dict[str, Any] | None = None,
        event_sink: Callable[[MultiAgentTraceEvent], None] | None = None,
        control: AgentRunControl | None = None,
        resuming: bool = False,
        precomputed_results: Sequence[TaskResult] | None = None,
        _collector: MultiAgentTraceCollector | None = None,
        supervisor_started: bool = False,
    ) -> ResearchOrchestrationRun:
        """Execute the Root-validated plan using the existing task executor."""

        context = dict(runtime_context or {})
        collector = _collector or MultiAgentTraceCollector(
            run_id=run_id, trace_id=trace_id, event_sink=event_sink
        )
        if control is not None:
            control.checkpoint("orchestration_prepared_start")
        if resuming:
            if task_plan is None:
                raise AgentRuntimeError(
                    "A resumed native orchestration run has no validated plan.",
                    stage="checkpoint",
                    fallback_reason="prepared_plan_missing",
                )
            scope, memory_snapshot = self.revalidate_prepared(
                profile_id=profile_id,
                scope=scope,
                task_plan=task_plan,
                run_id=collector.run_id,
                runtime_context=context,
            )
        elif memory_snapshot is None:
            memory_snapshot = self.load_memory_snapshot(
                profile_id=profile_id,
                scope=scope,
                run_id=collector.run_id,
                runtime_context=context,
            )
        memory_snapshot = dict(memory_snapshot or {})
        if (
            route.lane is not OrchestrationLane.FAST
            and task_plan is None
            and not route.missing_information
        ):
            raise AgentRuntimeError(
                "The Root plan is missing before specialist execution.",
                stage="planning",
                fallback_reason="prepared_plan_missing",
            )
        if task_plan is not None and task_plan.scope_ref != scope.scope_ref:
            raise AgentRuntimeError(
                "The prepared plan no longer matches its authoritative scope.",
                stage="planning",
                fallback_reason="prepared_scope_changed",
            )
        if precomputed_results is None and task_plan is not None:
            dynamic_tasks = [task.task_id for task in task_plan.tasks if task.role is None]
            if dynamic_tasks:
                raise AgentRuntimeError(
                    "Dynamic Agents require the native Send dispatcher.",
                    stage="orchestration",
                    fallback_reason="dynamic_agent_requires_native_dispatch",
                )

        temporary = bool(context.get("temporary", False))
        native_results_supplied = precomputed_results is not None
        if not native_results_supplied and not supervisor_started:
            collector.emit(
                "supervisor_started",
                actor="supervisor",
                status="running",
                payload={"lane": route.lane.value, "scope_ref": scope.scope_ref},
            )
        if not native_results_supplied:
            collector.emit(
                "supervisor_planned",
                actor="supervisor",
                status="complete",
                payload={
                    "lane": route.lane.value,
                    "task_count": len(task_plan.tasks) if task_plan else 0,
                    "agents": [task.agent_id for task in task_plan.tasks]
                    if task_plan
                    else [],
                },
            )
        if task_plan is not None and not native_results_supplied:
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
                    actor=task.agent_id,
                    status="pending",
                    payload={
                        "task_id": task.task_id,
                        "parent_task_id": "",
                        "role": task.agent_id,
                        "depends_on": list(task.depends_on),
                        "required": task.required,
                        "output_kind": task.expected_output_kind.value,
                        "attempt": 0,
                        "plan_revision": task.plan_revision,
                        "reason_code": "",
                        "usage": {},
                    },
                )
        if route.lane is OrchestrationLane.FAST or task_plan is None:
            execution_results: tuple[TaskResult, ...] = ()
            outputs: dict[str, Any] = {}
            direct_output = (
                "This research action needs additional scoped input before it can run: "
                + ", ".join(route.missing_information)
                if route.missing_information
                else None
            )
            direct_delivery = bool(route.missing_information)
        elif native_results_supplied:
            expected_task_ids = set(task_plan.task_map())
            by_id: dict[str, TaskResult] = {}
            for raw in precomputed_results or ():
                result = (
                    raw
                    if isinstance(raw, TaskResult)
                    else TaskResult.model_validate(raw)
                )
                if result.task_id not in expected_task_ids:
                    raise AgentRuntimeError(
                        "A native Root result is not part of the validated plan.",
                        stage="orchestration",
                        fallback_reason="native_result_unknown_task",
                    )
                previous = by_id.get(result.task_id)
                if previous is not None and previous.content_hash != result.content_hash:
                    raise AgentRuntimeError(
                        "The native Root returned conflicting task results.",
                        stage="orchestration",
                        fallback_reason="native_result_conflict",
                    )
                by_id[result.task_id] = result
            if set(by_id) != expected_task_ids:
                raise AgentRuntimeError(
                    "The native Root result set does not match the validated plan.",
                    stage="orchestration",
                    fallback_reason="native_results_incomplete",
                )
            if control is not None:
                control.checkpoint("native_results_verified")
            execution_results = tuple(
                by_id[task.task_id] for task in task_plan.tasks
            )
            outputs: dict[str, Any] = {}
            executor = (
                self.temporary_executor
                if temporary and self.temporary_executor is not None
                else self.executor
            )
            artifact_store = getattr(executor, "_artifacts", None) or self.artifact_store
            for task in task_plan.tasks:
                result = by_id[task.task_id]
                for ref in result.artifact_refs:
                    if ref.kind is not task.expected_output_kind:
                        raise AgentRuntimeError(
                            "A native artifact is outside the task output contract.",
                            stage="artifact",
                            fallback_reason="native_artifact_kind_mismatch",
                        )
                    if artifact_store is None:
                        raise AgentRuntimeError(
                            "The native artifact store is unavailable.",
                            stage="artifact",
                            fallback_reason="artifact_store_unavailable",
                        )
                    artifact = artifact_store.get(ref.artifact_id, ref.version)
                    if (
                        artifact is None
                        or artifact.content_hash != ref.content_hash
                        or artifact.scope_ref != scope.scope_ref
                        or artifact.producer_task_id != task.task_id
                        or artifact.kind is not ref.kind
                    ):
                        raise AgentRuntimeError(
                            "A native artifact failed scope or identity verification.",
                            stage="artifact",
                            fallback_reason="native_artifact_verification_failed",
                        )
                    outputs[task.task_id] = artifact.model_dump(mode="json")
            non_leaf = {
                dependency
                for task in task_plan.tasks
                for dependency in task.depends_on
            }
            direct_output = None
            direct_delivery = False
            for task in task_plan.tasks:
                result = by_id[task.task_id]
                if (
                    task.task_id not in non_leaf
                    and result.status.value in {"succeeded", "partial"}
                    and task.task_id in outputs
                ):
                    direct_output = outputs[task.task_id]
                    direct_delivery = True
            submit_candidates = getattr(self.memory_port, "submit_candidates", None)
            if callable(submit_candidates):
                candidate_arguments: dict[str, Any] = {
                    "profile_id": profile_id,
                    "workspace_id": scope.workspace_id,
                    "artifact_refs":[
                        ref for result in execution_results for ref in result.artifact_refs
                    ],
                    "temporary": temporary,
                }
                if "scope_ref" in inspect.signature(submit_candidates).parameters:
                    candidate_arguments["scope_ref"] = scope.scope_ref
                if control is not None:
                    control.commit_if_active(
                        "memory_candidate_submission",
                        lambda: submit_candidates(**candidate_arguments),
                    )
                else:
                    submit_candidates(**candidate_arguments)
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
                    actor=task_plan.task_map()[result.task_id].agent_id,
                    status=result.status.value,
                    payload={"task_id": result.task_id, "error_code": result.error_code},
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
                if control is not None:
                    control.commit_if_active(
                        "memory_candidate_submission",
                        lambda: submit_candidates(**candidate_arguments),
                    )
                else:
                    submit_candidates(**candidate_arguments)
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
        return self.execute_prepared(
            route=route,
            scope=scope,
            memory_snapshot=memory_snapshot,
            task_plan=task_plan,
            profile_id=profile_id,
            run_id=collector.run_id,
            trace_id=collector.trace_id,
            runtime_context=context,
            control=control,
            _collector=collector,
            supervisor_started=True,
        )

    def prepare_task_retry(self, state: Any, task_id: str) -> tuple[str, ...]:
        plan_payload = dict(getattr(state, "orchestration_plan", {}) or {})
        if not plan_payload:
            raise ValueError("run has no validated orchestration plan")
        plan = ValidatedTaskPlan.model_validate(plan_payload)
        scope_ref = str(
            dict(getattr(state, "orchestration_scope", {}) or {}).get("scope_ref", "")
            or ""
        )
        if scope_ref != plan.scope_ref:
            raise ValueError("persisted run scope no longer matches its task plan")
        prepare = getattr(self.executor, "prepare_retry", None)
        if not callable(prepare):
            raise TypeError("task retry is unavailable for this executor")
        return tuple(prepare(run_id=state.run_id, plan=plan, task_id=task_id))


__all__ = ["ResearchOrchestrationRun", "ResearchOrchestrationService"]
