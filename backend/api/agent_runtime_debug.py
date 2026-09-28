from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.agent_core.runtime import AgentRuntime
from backend.api.agent_dependencies import get_agent_runtime
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.api.agent_runtime_jobs import get_agent_run_store
from backend.models.agent_runtime_debug import (
    AgentRuntimeDebugArtifactRef,
    AgentRuntimeDebugAttempt,
    AgentRuntimeDebugEvent,
    AgentRuntimeDebugPlan,
    AgentRuntimeDebugRelatedIds,
    AgentRuntimeDebugRoute,
    AgentRuntimeDebugRunDetail,
    AgentRuntimeDebugRunSummary,
    AgentRuntimeDebugTask,
)
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_trace_store_service import (
    AgentTraceStoreService,
    StoredAgentEvent,
    StoredAgentRun,
)

router = APIRouter(prefix="/api/agent/runtime/debug", tags=["agent-runtime-debug"])
RunStoreDependency = Annotated[AgentRunStore, Depends(get_agent_run_store)]
TraceStoreDependency = Annotated[
    AgentTraceStoreService, Depends(get_agent_trace_store_service)
]
RuntimeDependency = Annotated[AgentRuntime, Depends(get_agent_runtime)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _strings(value: object) -> list[str] | None:
    if not isinstance(value, (tuple, list)):
        return None
    return [item for raw in value if (item := _text(raw)) is not None]


def _artifact_refs(value: object) -> list[AgentRuntimeDebugArtifactRef] | None:
    if not isinstance(value, (tuple, list)):
        return None
    refs: list[AgentRuntimeDebugArtifactRef] = []
    for raw in value:
        item = _mapping(raw)
        artifact_id = _text(item.get("artifact_id"))
        if artifact_id is None:
            continue
        refs.append(
            AgentRuntimeDebugArtifactRef(
                artifact_id=artifact_id,
                version=_integer(item.get("version")),
                kind=_text(item.get("kind")),
                content_hash=_text(item.get("content_hash")),
            )
        )
    return refs


def _event_status(event: StoredAgentEvent) -> str | None:
    status = _text(event.payload.get("status"))
    if status:
        return status
    if event.event_type.startswith("task_"):
        return event.event_type.removeprefix("task_")
    return None


def _safe_event(event: StoredAgentEvent) -> AgentRuntimeDebugEvent:
    payload = event.payload
    return AgentRuntimeDebugEvent(
        event_id=event.event_id,
        sequence=event.sequence,
        event_type=event.event_type,
        timestamp=event.timestamp,
        task_id=_text(payload.get("task_id")) or event.task_id or None,
        agent_id=event.agent_id or _text(payload.get("agent_id")),
        agent_version=event.agent_version,
        node_name=event.node_name,
        subgraph_path=event.subgraph_path,
        status=_event_status(event),
        attempt=_integer(payload.get("attempt")),
        duration_ms=_integer(payload.get("duration_ms")),
        tool_name=_text(payload.get("tool_name")) or _text(payload.get("name")),
        reason_code=_text(payload.get("reason_code")) or _text(payload.get("code")),
        recovery_reason=_text(payload.get("fallback_reason")),
    )


def _summary(
    run_id: str,
    *,
    durable: Any = None,
    trace: StoredAgentRun | None = None,
) -> AgentRuntimeDebugRunSummary:
    return AgentRuntimeDebugRunSummary(
        run_id=run_id,
        trace_id=(
            str(getattr(durable, "trace_id", "") or "")
            or (trace.trace_id if trace else "")
        ),
        task_id=_text(getattr(durable, "task_id", None)),
        status=(
            str(getattr(getattr(durable, "status", None), "value", "") or "")
            or (trace.status if trace else "unknown")
        ),
        engine=_text(getattr(durable, "engine", None)),
        graph_version=_text(getattr(durable, "graph_version", None)),
        state_schema_version=(
            version
            if (version := _integer(getattr(durable, "state_schema_version", None)))
            and version > 0
            else None
        ),
        created_at=(
            durable.created_at.isoformat()
            if getattr(durable, "created_at", None) is not None
            else (trace.created_at if trace else None)
        ),
        updated_at=(
            durable.updated_at.isoformat()
            if getattr(durable, "updated_at", None) is not None
            else None
        ),
        started_at=(
            durable.started_at.isoformat()
            if getattr(durable, "started_at", None) is not None
            else None
        ),
        finished_at=(
            durable.finished_at.isoformat()
            if getattr(durable, "finished_at", None) is not None
            else None
        ),
        duration_ms=(trace.total_duration_ms if trace and trace.total_duration_ms > 0 else None),
        event_count=(trace.event_count if trace else None),
        failure_reason=(trace.fallback_reason or None) if trace else None,
    )


def _task_summaries(
    snapshot: Mapping[str, Any], events: tuple[StoredAgentEvent, ...]
) -> tuple[AgentRuntimeDebugPlan | None, list[AgentRuntimeDebugTask] | None]:
    raw_plan = _mapping(snapshot.get("task_plan"))
    raw_tasks = raw_plan.get("tasks")
    task_records = [dict(item) for item in raw_tasks if isinstance(item, Mapping)] if isinstance(raw_tasks, list) else []
    result_records = [dict(item) for item in snapshot.get("task_results", ()) if isinstance(item, Mapping)] if isinstance(snapshot.get("task_results"), (list, tuple)) else []
    status_map = _mapping(snapshot.get("task_status_by_id"))
    result_map = {
        str(item.get("task_id", "")): item
        for item in result_records
        if _text(item.get("task_id"))
    }

    attempts_by_task: dict[str, dict[int | None, AgentRuntimeDebugAttempt]] = defaultdict(dict)
    for event in events:
        task_id = _text(event.payload.get("task_id"))
        attempt_number = _integer(event.payload.get("attempt"))
        if (
            not task_id
            or not event.event_type.startswith("task_")
            or attempt_number is None
            or attempt_number < 1
        ):
            continue
        current = attempts_by_task[task_id].get(attempt_number)
        attempts_by_task[task_id][attempt_number] = AgentRuntimeDebugAttempt(
            attempt=attempt_number,
            status=_event_status(event),
            duration_ms=_integer(event.payload.get("duration_ms"))
            or (current.duration_ms if current else None),
            error_code=_text(event.payload.get("reason_code"))
            or (current.error_code if current else None),
        )

    task_ids = {str(item.get("task_id", "")) for item in task_records if _text(item.get("task_id"))}
    task_ids.update(result_map)
    task_ids.update(attempts_by_task)
    safe_tasks: list[AgentRuntimeDebugTask] = []
    for task in task_records:
        task_id = _text(task.get("task_id"))
        if task_id is None:
            continue
        result = result_map.get(task_id, {})
        usage = _mapping(result.get("usage"))
        refs = _artifact_refs(result.get("artifact_refs"))
        attempt_map = attempts_by_task.get(task_id, {})
        result_attempt = _integer(result.get("attempt_ordinal"))
        if result_attempt is not None and result_attempt not in attempt_map:
            attempt_map[result_attempt] = AgentRuntimeDebugAttempt(
                attempt=result_attempt,
                status=_text(result.get("status")),
                duration_ms=_integer(usage.get("elapsed_ms")),
                error_code=_text(result.get("error_code")),
            )
        safe_tasks.append(
            AgentRuntimeDebugTask(
                task_id=task_id,
                agent_id=_text(task.get("agent_id")) or _text(task.get("role")),
                status=_text(status_map.get(task_id)) or _text(result.get("status")),
                depends_on=_strings(task.get("depends_on")),
                required=task.get("required") if isinstance(task.get("required"), bool) else None,
                output_kind=_text(task.get("expected_output_kind")),
                attempts=sorted(attempt_map.values(), key=lambda item: item.attempt or -1) or None,
                artifact_refs=refs,
                duration_ms=_integer(usage.get("elapsed_ms")),
                failure_reason=_text(result.get("error_code")),
            )
        )
    if not safe_tasks:
        for task_id in sorted(task_ids):
            result = result_map.get(task_id, {})
            attempt_map = attempts_by_task.get(task_id, {})
            safe_tasks.append(
                AgentRuntimeDebugTask(
                    task_id=task_id,
                    status=_text(status_map.get(task_id)) or _text(result.get("status")),
                    attempts=sorted(attempt_map.values(), key=lambda item: item.attempt or -1) or None,
                    artifact_refs=_artifact_refs(result.get("artifact_refs")),
                    duration_ms=_integer(_mapping(result.get("usage")).get("elapsed_ms")),
                    failure_reason=_text(result.get("error_code")),
                )
            )

    plan = None
    if raw_plan:
        plan = AgentRuntimeDebugPlan(
            plan_id=_text(raw_plan.get("plan_id")),
            plan_revision=_integer(raw_plan.get("plan_revision")),
            task_count=len(task_records) if isinstance(raw_tasks, list) else None,
        )
    return plan, safe_tasks or None


def _safe_route(snapshot: Mapping[str, Any]) -> AgentRuntimeDebugRoute | None:
    route = _mapping(snapshot.get("orchestration_route"))
    if not route:
        return None
    return AgentRuntimeDebugRoute(
        lane=_text(route.get("lane")),
        route_kind=_text(route.get("route_kind")),
        reason_code=_text(route.get("reason_code")),
    )


@router.get("/runs", response_model=list[AgentRuntimeDebugRunSummary])
def list_runtime_debug_runs(
    store: RunStoreDependency,
    trace_store: TraceStoreDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AgentRuntimeDebugRunSummary]:
    durable_runs = {run.run_id: run for run in store.list_recent_runs(limit=limit)}
    trace_runs = {run.run_id: run for run in trace_store.list_recent(limit=limit)}
    run_ids = list(dict.fromkeys([*durable_runs, *trace_runs]))[:limit]
    summaries = [
        _summary(run_id, durable=durable_runs.get(run_id), trace=trace_runs.get(run_id))
        for run_id in run_ids
    ]
    return sorted(summaries, key=lambda item: item.created_at or "", reverse=True)


@router.get("/runs/{run_id}", response_model=AgentRuntimeDebugRunDetail)
def get_runtime_debug_run(
    run_id: str,
    store: RunStoreDependency,
    trace_store: TraceStoreDependency,
    runtime: RuntimeDependency,
) -> AgentRuntimeDebugRunDetail:
    durable = store.get_run(run_id)
    trace = trace_store.get_run(run_id)
    if durable is None and trace is None:
        raise HTTPException(status_code=404, detail="Run not found")

    stored_events = trace_store.list_events(run_id)
    safe_events = [_safe_event(event) for event in stored_events]
    snapshot: Mapping[str, Any] = {}
    try:
        resolved = runtime.checkpoint_orchestration_state(run_id)
        if isinstance(resolved, Mapping):
            snapshot = resolved
    except Exception:  # noqa: BLE001 - Debug projection must not affect runtime state.
        snapshot = {}
    plan, tasks = _task_summaries(snapshot, stored_events)
    tool_names = sorted(
        {
            tool_name
            for event in safe_events
            if (tool_name := event.tool_name) is not None
        }
    )
    rag_ids = sorted(
        {
            query_id
            for event in stored_events
            if event.event_type.startswith("rag_")
            and (query_id := _text(event.payload.get("query_id"))) is not None
        }
    )
    sandbox_ids = sorted(
        {
            sandbox_id
            for event in stored_events
            if (sandbox_id := _text(event.payload.get("sandbox_id"))) is not None
        }
    )
    failure_reason = next(
        (
            reason
            for event in reversed(stored_events)
            if event.event_type in {"failure", "task_failed", "task_blocked"}
            and (reason := _text(event.payload.get("reason_code")) or _text(event.payload.get("code")))
        ),
        None,
    )
    recovery_reason = next(
        (
            reason
            for event in reversed(stored_events)
            if (reason := _text(event.payload.get("fallback_reason"))) is not None
        ),
        None,
    )
    summary = _summary(run_id, durable=durable, trace=trace)
    summary.failure_reason = failure_reason or summary.failure_reason
    summary.recovery_reason = recovery_reason
    return AgentRuntimeDebugRunDetail(
        **summary.model_dump(),
        route=_safe_route(snapshot),
        plan=plan,
        tasks=tasks,
        tool_names=tool_names or None,
        related_ids=AgentRuntimeDebugRelatedIds(
            rag_query_ids=rag_ids or None,
            sandbox_ids=sandbox_ids or None,
        ),
        events=safe_events,
    )


__all__ = ["get_runtime_debug_run", "list_runtime_debug_runs", "router"]
