from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from hashlib import sha256
from time import perf_counter
from typing import Any, NotRequired

from langgraph.config import get_config
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentBudgetExceededError, AgentCancelledError
from backend.agent_core.orchestration.frontier import dependency_results
from backend.agent_core.orchestration.resource_manager import AgentResourceManager
from backend.agent_core.orchestration.runtime_budget import bind_runtime_budget
from backend.models.agent_tasks import (
    ScopeContext,
    TaskResult,
    TaskSpec,
    TaskStatus,
    utc_now,
)
from backend.rag.observability import bind_rag_trace, current_rag_trace


class SpecialistDispatchInput(TypedDict):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    trace_id: NotRequired[str]


def specialist_node_name(agent_id: str) -> str:
    """Map a stable registry ID to a deterministic, graph-safe node name."""

    normalized = str(agent_id or "").strip()
    if not normalized:
        raise ValueError("agent_id is required for a specialist node")
    safe = "".join(char.lower() if char.isalnum() else "_" for char in normalized)
    safe = "_".join(part for part in safe.split("_") if part)[:48] or "agent"
    suffix = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"specialist_{safe}_{suffix}"


def resolve_compiled_graph(agent_id: str, graph_factory: Any) -> Any:
    if not callable(graph_factory):
        raise TypeError(f"Agent {agent_id} has no registered graph factory")
    instance = graph_factory()
    compiled = getattr(instance, "compiled_graph", None)
    if compiled is None:
        compiled = instance
    if not callable(getattr(compiled, "invoke", None)):
        raise TypeError(
            f"Agent {agent_id} graph_factory must return a compiled graph or graph adapter"
        )
    return compiled


def resolve_per_invocation_graph(agent_id: str, compiled_graph: Any) -> Any:
    """Compile a specialist for persistent per-invocation subgraph state.

    LangGraph's ``checkpointer=True`` inherits the active parent saver while
    assigning a checkpoint namespace to this specialist invocation. A concrete
    saver on a specialist is rejected: Root owns the one shared SQLite saver.
    """

    if not isinstance(compiled_graph, CompiledStateGraph):
        raise TypeError(
            f"Agent {agent_id} must return a compiled LangGraph for checkpointed execution"
        )
    if compiled_graph.checkpointer is True:
        return compiled_graph
    if compiled_graph.checkpointer is not None:
        raise TypeError(
            f"Agent {agent_id} must inherit the Root checkpointer, not own one"
        )
    builder = getattr(compiled_graph, "builder", None)
    compile_graph = getattr(builder, "compile", None)
    if not callable(compile_graph):
        raise TypeError(f"Agent {agent_id} graph cannot enable per-invocation checkpoints")
    checkpointed = compile_graph(checkpointer=True)
    if not isinstance(checkpointed, CompiledStateGraph) or checkpointed.checkpointer is not True:
        raise TypeError(f"Agent {agent_id} did not enable per-invocation checkpoints")
    return checkpointed


def _typed_dependencies(
    raw: Mapping[str, Any], task: TaskSpec
) -> dict[str, TaskResult]:
    projection = dependency_results(task, raw)
    if projection.missing_task_ids:
        raise ValueError(
            "specialist dispatch has unresolved dependencies: "
            + ", ".join(projection.missing_task_ids)
        )
    if projection.failed_task_ids:
        raise ValueError(
            "failed dependencies must be reduced before specialist dispatch: "
            + ", ".join(projection.failed_task_ids)
        )
    return dict(projection.results)


def _memory_projection(snapshot: Any, agent_id: str) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {"role_projections": {agent_id: []}}
    # The memory port already returned a scope-filtered frozen snapshot. Keep
    # its specialist-specific material available to the real subgraph; the
    # snapshot body lives only in invocation context, never in Root channels.
    return copy.deepcopy(dict(snapshot))


def specialist_memory_snapshot(
    runtime: Runtime[Any] | None, state: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Read the frozen memory body from invocation context, with legacy fallback."""

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        snapshot = context.get("memory_snapshot")
        if isinstance(snapshot, Mapping):
            return snapshot
    snapshot = state.get("memory_snapshot", {})
    return snapshot if isinstance(snapshot, Mapping) else {}


def commit_specialist_effect(
    runtime: Runtime[Any] | None,
    stage: str,
    operation: Any,
) -> Any:
    """Commit one short specialist side effect only while its Root run is active."""

    context = getattr(runtime, "context", None)
    control = context.get("control") if isinstance(context, Mapping) else None
    commit = getattr(control, "commit_if_active", None)
    if callable(commit):
        return commit(stage, operation)
    return operation()


def _normalize_result(
    result: TaskResult,
    task: TaskSpec,
    *,
    started_at: Any,
    attempt_ordinal: int,
) -> TaskResult:
    if result.task_id != task.task_id:
        raise ValueError("specialist returned a result for a different task")
    for ref in result.artifact_refs:
        if ref.kind != task.expected_output_kind:
            raise ValueError(
                f"Agent {task.agent_id} returned an artifact outside the task output contract"
            )
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload.update(
        {
            "attempt_id": f"{task.task_id}:{attempt_ordinal}",
            "attempt_ordinal": attempt_ordinal,
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    )
    return TaskResult.model_validate(payload)


def create_specialist_node(
    agent_spec: Any,
    compiled_graph: Any,
    *,
    checkpointed_graph: Any | None = None,
    temporary_graph: Any | None = None,
):
    """Create a Root-node adapter that invokes the registered compiled subgraph."""

    def execute(
        dispatch: SpecialistDispatchInput,
        runtime: Runtime[Any],
    ) -> dict[str, Any]:
        task = TaskSpec.model_validate(dispatch["task"])
        attempt_ordinal = max(1, int(dispatch.get("attempt_ordinal", 1)))
        if task.agent_id != agent_spec.agent_id:
            raise ValueError("dispatched task Agent does not match target subgraph")
        if not set(task.allowed_tools) <= set(agent_spec.allowed_tools):
            raise PermissionError("task Tool allowlist exceeds the registered Agent")
        scope = ScopeContext.model_validate(dispatch["scope"])
        if task.scope_ref != scope.scope_ref:
            raise PermissionError("dispatched task does not match the authoritative scope")
        dependencies = _typed_dependencies(dispatch.get("dependency_results", {}), task)
        context = runtime.context if isinstance(runtime.context, Mapping) else {}
        manager = context.get("resource_manager")
        if not isinstance(manager, AgentResourceManager):
            manager = AgentResourceManager(
                context.get("parallel_policy") or _DEFAULT_RESOURCE_POLICY
            )
        control = context.get("control")
        if control is not None:
            control.pause_at_boundary(f"native_specialist:{task.task_id}")
            control.checkpoint(f"native_specialist:{task.task_id}:start")
        emit = context.get("event_sink")
        if callable(emit):
            emit(
                AgentEventType.TASK_STARTED,
                {
                    "task_id": task.task_id,
                    "agent_id": task.agent_id,
                    "status": "running",
                    "attempt": attempt_ordinal,
                },
            )
        started_at = utc_now()
        started_clock = perf_counter()
        try:
            temporary = bool(context.get("temporary"))
            use_checkpointed_graph = bool(context.get("persistent_checkpoints"))
            active_graph = (
                temporary_graph
                if temporary
                else checkpointed_graph
                if use_checkpointed_graph
                else compiled_graph
            )
            if active_graph is None:
                raise RuntimeError(
                    
                        f"Agent {agent_spec.agent_id} has no temporary artifact graph"
                        if temporary
                        else f"Agent {agent_spec.agent_id} has no shared-checkpointer graph"
                    
                )
            child_input = {
                "task": task,
                "scope": scope,
                "dependency_results": dependencies,
            }
            if not use_checkpointed_graph:
                # The temporary graph has no saver. Preserve the standalone
                # specialist input contract without putting memory in durable
                # native subgraph checkpoints.
                child_input["memory_snapshot"] = _memory_projection(
                    context.get("memory_snapshot", {}), task.agent_id
                )
            with manager.acquire(agent_spec.resource_class), bind_runtime_budget(
                manager.budget
            ), bind_rag_trace(
                dispatch.get("trace_id") or current_rag_trace()[0], emit
            ):
                if use_checkpointed_graph:
                    parent_config = get_config()
                    child_config = dict(parent_config)
                    configurable = dict(parent_config.get("configurable", {}))
                    parent_namespace = str(
                        configurable.get("checkpoint_ns", "") or ""
                    )
                    structural_namespace = "|".join(
                        part.split(":", 1)[0]
                        for part in parent_namespace.split("|")
                        if part and not part.isdigit()
                    )
                    namespace_identity = (
                        task.task_id
                        if attempt_ordinal == 1
                        else f"{task.task_id}:{attempt_ordinal}"
                    )
                    task_namespace = sha256(
                        namespace_identity.encode("utf-8")
                    ).hexdigest()[:16]
                    configurable["checkpoint_ns"] = "|".join(
                        part
                        for part in (structural_namespace, f"task_{task_namespace}")
                        if part
                    )
                    configurable.pop("checkpoint_id", None)
                    child_config["configurable"] = configurable
                    final = active_graph.invoke(
                        child_input, config=child_config, durability="sync"
                    )
                else:
                    final = active_graph.invoke(child_input)
            result = TaskResult.model_validate(final["result"])
            result = _normalize_result(
                result,
                task,
                started_at=started_at,
                attempt_ordinal=attempt_ordinal,
            )
            manager.budget.record(
                result.model_copy(
                    update={
                        "usage": result.usage.model_copy(
                            update={
                                "elapsed_ms": int(
                                    (perf_counter() - started_clock) * 1000
                                )
                            }
                        )
                    }
                ).usage
            )
        except AgentCancelledError:
            raise
        except AgentBudgetExceededError:
            result = TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:{attempt_ordinal}",
                attempt_ordinal=attempt_ordinal,
                status=TaskStatus.BLOCKED,
                error_code="budget_exhausted",
            )
        except Exception as exc:  # noqa: BLE001 - specialist failure is isolated
            result = TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:{attempt_ordinal}",
                attempt_ordinal=attempt_ordinal,
                status=TaskStatus.FAILED,
                error_code=type(exc).__name__,
            )

        if control is not None:
            control.checkpoint(f"native_specialist:{task.task_id}:complete")
        if callable(emit):
            event = (
                AgentEventType.TASK_COMPLETED
                if result.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL}
                else AgentEventType.TASK_FAILED
            )
            emit(
                event,
                {
                    "task_id": task.task_id,
                    "agent_id": task.agent_id,
                    "status": result.status.value,
                    "attempt": result.attempt_ordinal,
                    "reason_code": result.error_code,
                },
            )
        return {
            "task_results": [result.model_dump(mode="json")],
            "task_status_by_id": {task.task_id: result.status.value},
            "artifact_refs": [
                ref.model_dump(mode="json") for ref in result.artifact_refs
            ],
            "evidence_refs": [
                ref.model_dump(mode="json") for ref in result.evidence_refs
            ],
        }

    execute.input_schema = SpecialistDispatchInput  # type: ignore[attr-defined]
    return execute


class _DefaultResourcePolicy:
    max_parallel_experts = 2
    max_model_calls = 8
    max_tool_calls = 16
    max_retrievals = 8


_DEFAULT_RESOURCE_POLICY = _DefaultResourcePolicy()


__all__ = [
    "SpecialistDispatchInput",
    "commit_specialist_effect",
    "create_specialist_node",
    "resolve_compiled_graph",
    "resolve_per_invocation_graph",
    "specialist_memory_snapshot",
    "specialist_node_name",
]
