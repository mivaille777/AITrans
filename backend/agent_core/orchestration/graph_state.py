from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from typing_extensions import TypedDict

from backend.agent_core.orchestration.reducer import (
    reduce_artifact_refs as _reduce_artifact_refs,
)
from backend.agent_core.orchestration.reducer import (
    reduce_event_fingerprints,
    reduce_task_results,
)
from backend.agent_core.orchestration.reducer import (
    reduce_event_ids as _reduce_event_ids,
)
from backend.agent_core.orchestration.reducer import (
    reduce_evidence_refs as _reduce_evidence_refs,
)
from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
    LEGACY_AGENT_GRAPH_VERSION,
    SUPPORTED_AGENT_GRAPH_VERSIONS,
)
from backend.models.agent_tasks import ScopeContext, TaskResult, ValidatedTaskPlan


def _scope_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return ScopeContext.model_validate(dict(value)).model_dump(mode="json")


def _plan_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return ValidatedTaskPlan.model_validate(dict(value)).model_dump(mode="json")


def reduce_task_result_payloads(
    existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """LangGraph reducer for the canonical, JSON-serialized TaskResult list."""

    left = [TaskResult.model_validate(item) for item in existing]
    right = [TaskResult.model_validate(item) for item in incoming]
    return [item.model_dump(mode="json") for item in reduce_task_results(left, right)]


def reduce_artifact_refs(
    existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """LangGraph reducer for immutable artifact versions."""

    return [
        item.model_dump(mode="json")
        for item in _reduce_artifact_refs(existing, incoming)
    ]


def reduce_evidence_refs(
    existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """LangGraph reducer for immutable evidence identities."""

    return [
        item.model_dump(mode="json")
        for item in _reduce_evidence_refs(existing, incoming)
    ]


def reduce_event_ids(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    """Return stable, idempotent event identity accumulation."""

    return list(_reduce_event_ids(existing, incoming))


def reduce_task_status_by_id(
    existing: Mapping[str, str], incoming: Mapping[str, str]
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in existing.items()}
    for key, value in incoming.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key and normalized_value:
            merged[normalized_key] = normalized_value
    return merged


def reduce_frontier_task_ids(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    return sorted({str(item).strip() for item in [*existing, *incoming] if str(item).strip()})


class RootOrchestrationState(TypedDict, total=False):
    """Checkpoint-safe orchestration channels owned by the Root Graph.

    Large artifacts and runtime/service objects are intentionally absent. All
    fields are identifiers, versions, control state, or immutable references.
    """

    graph_version: str
    engine: str
    state_schema_version: int
    orchestration_route: dict[str, Any]
    scope: dict[str, Any]
    plan_revision: int
    memory_policy_revision: str
    memory_snapshot_ref: str
    task_plan: dict[str, Any]
    task_results: Annotated[list[dict[str, Any]], reduce_task_result_payloads]
    task_status_by_id: Annotated[dict[str, str], reduce_task_status_by_id]
    task_attempt_ordinals: dict[str, int]
    retry_task_ids: list[str]
    frontier_task_ids: Annotated[list[str], reduce_frontier_task_ids]
    active_frontier_task_ids: list[str]
    artifact_refs: Annotated[list[dict[str, Any]], reduce_artifact_refs]
    evidence_refs: Annotated[list[dict[str, Any]], reduce_evidence_refs]
    event_ids: Annotated[list[str], reduce_event_ids]
    event_fingerprints: Annotated[dict[str, str], reduce_event_fingerprints]
    orchestration_status: str


def initial_orchestration_state(
    *,
    scope: Mapping[str, Any] | None = None,
    task_plan: Mapping[str, Any] | None = None,
    task_results: Iterable[Mapping[str, Any]] = (),
    orchestration_status: str = "idle",
    memory_snapshot_ref: str = "",
    graph_version: str = CURRENT_AGENT_GRAPH_VERSION,
    state_schema_version: int = CURRENT_AGENT_STATE_SCHEMA_VERSION,
    engine: str = "compat",
) -> RootOrchestrationState:
    results = tuple(TaskResult.model_validate(item) for item in task_results)
    return {
        "graph_version": str(graph_version),
        "engine": str(engine or "compat"),
        "state_schema_version": int(state_schema_version),
        "orchestration_route": {},
        "scope": _scope_payload(scope),
        "plan_revision": int(
            (task_plan or {}).get("plan_revision", 0)
            if isinstance(task_plan, Mapping)
            else 0
        ),
        "memory_policy_revision": str(
            (scope or {}).get("memory_policy_revision", "")
            if isinstance(scope, Mapping)
            else ""
        ),
        "memory_snapshot_ref": str(memory_snapshot_ref or ""),
        "task_plan": _plan_payload(task_plan),
        "task_results": [item.model_dump(mode="json") for item in results],
        "task_status_by_id": {
            item.task_id: item.status.value for item in results
        },
        "task_attempt_ordinals": {
            item.task_id: max(
                item.attempt_ordinal,
                max(
                    (
                        result.attempt_ordinal
                        for result in results
                        if result.task_id == item.task_id
                    ),
                    default=1,
                ),
            )
            for item in results
        },
        "retry_task_ids": [],
        "frontier_task_ids": [],
        "active_frontier_task_ids": [],
        "artifact_refs": reduce_artifact_refs(
            (),
            [
                ref
                for item in results
                for ref in item.artifact_refs
            ],
        ),
        "evidence_refs": reduce_evidence_refs(
            (),
            [
                ref
                for item in results
                for ref in item.evidence_refs
            ],
        ),
        "event_ids": [],
        "event_fingerprints": {},
        "orchestration_status": str(orchestration_status or "idle"),
    }


def checkpoint_graph_version(raw_snapshot: Mapping[str, Any]) -> str:
    """Select a builder from raw checkpoint channels before state migration."""

    payload = raw_snapshot.get("values", raw_snapshot)
    if not isinstance(payload, Mapping):
        payload = {}
    raw_state = payload.get("agent_state", {})
    if not isinstance(raw_state, Mapping):
        raw_state = {}
    version = str(
        payload.get("graph_version")
        or raw_state.get("graph_version")
        or LEGACY_AGENT_GRAPH_VERSION
    ).strip()
    if version not in SUPPORTED_AGENT_GRAPH_VERSIONS:
        raise ValueError(f"unsupported Agent graph_version: {version}")
    return version


def checkpoint_state_schema_version(raw_snapshot: Mapping[str, Any]) -> int:
    payload = raw_snapshot.get("values", raw_snapshot)
    if not isinstance(payload, Mapping):
        payload = {}
    raw_state = payload.get("agent_state", {})
    if not isinstance(raw_state, Mapping):
        raw_state = {}
    raw_version = payload.get("state_schema_version") or raw_state.get(
        "state_schema_version", 1
    )
    version = int(raw_version or 1)
    if version < 1 or version > CURRENT_AGENT_STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported Agent state schema version: {version}")
    return version


def checkpoint_engine(raw_snapshot: Mapping[str, Any]) -> str:
    """Read a checkpoint's execution engine; pre-MA05 checkpoints are compat."""

    payload = raw_snapshot.get("values", raw_snapshot)
    if not isinstance(payload, Mapping):
        payload = {}
    engine = str(payload.get("engine", "compat") or "compat").strip().lower()
    if engine not in {"compat", "native"}:
        raise ValueError(f"unsupported Agent engine: {engine}")
    return engine


def import_legacy_orchestration_state(
    legacy: Mapping[str, Any], *, prior: Mapping[str, Any] | None = None
) -> RootOrchestrationState:
    """Import the legacy bridge's projection at its compatibility boundary."""

    old_results = legacy.get("orchestration_results", ())
    results = [item for item in old_results if isinstance(item, Mapping)] if isinstance(
        old_results, (list, tuple)
    ) else []
    prior_state = prior or {}
    canonical_results = reduce_task_result_payloads(
        prior_state.get("task_results", ()), results
    )
    artifact_refs = [
        ref
        for result in canonical_results
        for ref in result.get("artifact_refs", ())
        if isinstance(ref, Mapping)
    ]
    evidence_refs = [
        ref
        for result in canonical_results
        for ref in result.get("evidence_refs", ())
        if isinstance(ref, Mapping)
    ]
    statuses = {
        str(result["task_id"]): str(result["status"])
        for result in canonical_results
        if result.get("task_id") and result.get("status")
    }
    return {
        "scope": _scope_payload(
            legacy.get("orchestration_scope") or prior_state.get("scope"),
        ),
        "memory_snapshot_ref": str(
            legacy.get("memory_snapshot_ref")
            or prior_state.get("memory_snapshot_ref", "")
            or ""
        ),
        "task_plan": _plan_payload(
            legacy.get("orchestration_plan") or prior_state.get("task_plan"),
        ),
        "task_results": canonical_results,
        "task_status_by_id": reduce_task_status_by_id(
            prior_state.get("task_status_by_id", {}), statuses
        ),
        "frontier_task_ids": list(prior_state.get("frontier_task_ids", ())),
        "active_frontier_task_ids": list(
            prior_state.get("active_frontier_task_ids", ())
        ),
        "artifact_refs": reduce_artifact_refs(
            prior_state.get("artifact_refs", ()), artifact_refs
        ),
        "evidence_refs": reduce_evidence_refs(
            prior_state.get("evidence_refs", ()), evidence_refs
        ),
        "event_ids": reduce_event_ids(prior_state.get("event_ids", ()), ()),
        "event_fingerprints": reduce_event_fingerprints(
            prior_state.get("event_fingerprints", {}), {}
        ),
        "orchestration_status": str(
            legacy.get("orchestration_status")
            or prior_state.get("orchestration_status", "idle")
            or "idle"
        ),
    }


def project_orchestration_state(
    canonical: Mapping[str, Any], *, legacy: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Project canonical Root channels onto the legacy AgentState field names."""

    fallback = legacy or {}
    scope = canonical.get("scope")
    task_plan = canonical.get("task_plan")
    task_results = canonical.get("task_results")
    scope_payload = (
        dict(scope)
        if "scope" in canonical and isinstance(scope, Mapping)
        else dict(fallback.get("orchestration_scope", {}) or {})
    )
    plan_payload = (
        dict(task_plan)
        if "task_plan" in canonical and isinstance(task_plan, Mapping)
        else dict(fallback.get("orchestration_plan", {}) or {})
    )
    results_payload = (
        [dict(item) for item in task_results if isinstance(item, Mapping)]
        if "task_results" in canonical and isinstance(task_results, (list, tuple))
        else [
            dict(item)
            for item in fallback.get("orchestration_results", ())
            if isinstance(item, Mapping)
        ]
    )
    return {
        "orchestration_scope": copy.deepcopy(scope_payload),
        "orchestration_plan": copy.deepcopy(plan_payload),
        "orchestration_results": copy.deepcopy(results_payload),
        "memory_snapshot_ref": str(
            canonical.get("memory_snapshot_ref", fallback.get("memory_snapshot_ref", ""))
            or ""
        ),
        "orchestration_status": str(
            canonical.get(
                "orchestration_status", fallback.get("orchestration_status", "idle")
            )
            or "idle"
        ),
    }


__all__ = [
    "RootOrchestrationState",
    "checkpoint_engine",
    "checkpoint_graph_version",
    "checkpoint_state_schema_version",
    "import_legacy_orchestration_state",
    "initial_orchestration_state",
    "project_orchestration_state",
    "reduce_artifact_refs",
    "reduce_event_fingerprints",
    "reduce_event_ids",
    "reduce_evidence_refs",
    "reduce_frontier_task_ids",
    "reduce_task_result_payloads",
    "reduce_task_status_by_id",
]
