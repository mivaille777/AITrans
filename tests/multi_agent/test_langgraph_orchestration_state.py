from __future__ import annotations

from typing import get_type_hints

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.graph_state import (
    RootOrchestrationState,
    initial_orchestration_state,
    project_orchestration_state,
    reduce_artifact_refs,
    reduce_event_ids,
    reduce_evidence_refs,
    reduce_task_result_payloads,
)
from backend.agent_core.orchestration.reducer import (
    EventIdentityConflictError,
    TaskResultConflictError,
    event_fingerprint,
    reduce_event_fingerprints,
)
from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
    LEGACY_AGENT_GRAPH_VERSION,
)
from backend.models.agent_run import AgentRunStatus
from backend.models.agent_tasks import TaskResult
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore


def _result(task_id: str, warning: str = "") -> dict[str, object]:
    return TaskResult(
        task_id=task_id,
        attempt_id="attempt-1",
        status="succeeded",
        warnings=[warning] if warning else [],
    ).model_dump(mode="json")


def test_root_state_has_only_serializable_orchestration_channels() -> None:
    annotations = get_type_hints(RootOrchestrationState, include_extras=True)

    assert {
        "graph_version",
        "state_schema_version",
        "scope",
        "memory_snapshot_ref",
        "task_plan",
        "task_results",
        "task_status_by_id",
        "frontier_task_ids",
        "artifact_refs",
        "evidence_refs",
        "event_ids",
        "event_fingerprints",
        "orchestration_status",
    } <= set(annotations)
    assert "runtime_context" not in annotations
    assert "service" not in annotations


def test_parallel_task_result_payloads_merge_idempotently_and_conflict_by_hash() -> None:
    a = _result("a")
    b = _result("b")

    merged = reduce_task_result_payloads([a], [b, a])

    assert [item["task_id"] for item in merged] == ["a", "b"]
    with pytest.raises(TaskResultConflictError):
        reduce_task_result_payloads([a], [_result("a", "different result")])


def test_artifact_refs_keep_versions_and_detect_same_version_conflicts() -> None:
    v1 = {
        "artifact_id": "outline-1",
        "version": 1,
        "kind": "outline",
        "content_hash": "hash-1",
    }
    v2 = {**v1, "version": 2, "content_hash": "hash-2"}

    merged = reduce_artifact_refs([v2], [v1, v2])

    assert [(item["artifact_id"], item["version"]) for item in merged] == [
        ("outline-1", 1),
        ("outline-1", 2),
    ]
    with pytest.raises(ValueError, match="conflicting artifact ref"):
        reduce_artifact_refs([v1], [{**v1, "content_hash": "other"}])


def test_event_ids_are_stably_deduplicated() -> None:
    assert reduce_event_ids(["event-b", "event-a"], ["event-a", "event-c"]) == [
        "event-a",
        "event-b",
        "event-c",
    ]


def test_evidence_refs_and_event_fingerprints_reject_identity_conflicts() -> None:
    evidence = {
        "evidence_id": "evidence-1",
        "source_id": "paper-1",
        "source_type": "document",
        "source_version": "v1",
        "source_hash": "hash-1",
        "locator": {"page": 1},
    }
    assert reduce_evidence_refs([evidence], [evidence]) == [evidence]
    with pytest.raises(ValueError, match="conflicting evidence ref"):
        reduce_evidence_refs([evidence], [{**evidence, "source_hash": "hash-2"}])

    first = {
        "event_id": "event-1",
        "event_type": "task_started",
        "run_id": "run-1",
        "task_id": "task-1",
        "sequence": 1,
        "payload": {"attempt": 1},
    }
    _, first_fingerprint = event_fingerprint(first)
    _, changed_fingerprint = event_fingerprint(
        {**first, "payload": {"attempt": 2}}
    )
    with pytest.raises(EventIdentityConflictError, match="conflicting event identity"):
        reduce_event_fingerprints(
            {"event-1": first_fingerprint},
            {"event-1": changed_fingerprint},
        )


def test_scope_channel_rejects_non_scope_payloads() -> None:
    with pytest.raises(ValueError):
        initial_orchestration_state(
            scope={
                "scope_ref": "scope:1",
                "scope_revision": "rev-1",
                "artifact_body": "not a reference",
            }
        )


def test_legacy_projection_is_one_way_and_preserves_snapshot_contract() -> None:
    canonical = {
        "scope": {"scope_ref": "scope:1", "scope_revision": "rev-1"},
        "task_plan": {"plan_id": "plan-1", "tasks": []},
        "task_results": [_result("a")],
        "memory_snapshot_ref": "memory:1",
        "orchestration_status": "running",
    }

    projected = project_orchestration_state(canonical)

    assert projected == {
        "orchestration_scope": canonical["scope"],
        "orchestration_plan": canonical["task_plan"],
        "orchestration_results": canonical["task_results"],
        "memory_snapshot_ref": "memory:1",
        "orchestration_status": "running",
    }
    assert "task_results" not in projected


def test_orchestration_state_round_trips_through_sqlite_checkpoint(tmp_path) -> None:
    state_type = RootOrchestrationState

    def persist(state):
        return {
            "scope": state["scope"],
            "task_plan": state["task_plan"],
            "task_results": [_result("a")],
            "artifact_refs": [
                {
                    "artifact_id": "analysis-1",
                    "version": 1,
                    "kind": "document_analysis",
                    "content_hash": "content-hash",
                }
            ],
        }

    builder = StateGraph(state_type)
    builder.add_node("persist", persist)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)
    path = tmp_path / "orchestration.sqlite3"
    with SqliteSaver.from_conn_string(str(path)) as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        graph.invoke(
            {
                "graph_version": CURRENT_AGENT_GRAPH_VERSION,
                "state_schema_version": CURRENT_AGENT_STATE_SCHEMA_VERSION,
                "scope": {"scope_ref": "scope:1", "scope_revision": "rev-1"},
                "memory_snapshot_ref": "memory:1",
                "task_plan": {"plan_id": "plan-1", "tasks": []},
                "task_results": [],
                "task_status_by_id": {"a": "pending"},
                "frontier_task_ids": ["a"],
            "artifact_refs": [],
            "evidence_refs": [],
            "event_ids": [],
            "event_fingerprints": {},
                "orchestration_status": "running",
            },
            config={"configurable": {"thread_id": "run-1"}},
        )
        loaded = graph.get_state({"configurable": {"thread_id": "run-1"}}).values

    assert loaded["scope"]["scope_ref"] == "scope:1"
    assert loaded["task_plan"]["plan_id"] == "plan-1"
    assert loaded["task_results"][0]["task_id"] == "a"
    assert loaded["artifact_refs"][0]["content_hash"] == "content-hash"
    assert "service" not in repr(loaded).lower()


def test_queued_run_pins_engine_and_graph_version_before_environment_changes(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT", "false")
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    run = AgentRunScheduler(store).enqueue(goal="Pin the selected runtime")

    assert run.engine == "compat"
    assert run.graph_version == CURRENT_AGENT_GRAPH_VERSION
    assert run.state_schema_version == CURRENT_AGENT_STATE_SCHEMA_VERSION

    monkeypatch.setenv("AITRANS_LANGGRAPH_NATIVE_MULTI_AGENT", "true")
    queued = store.get_run(run.run_id)
    assert queued is not None
    assert queued.engine == "compat"
    assert queued.graph_version == run.graph_version
    assert queued.state_schema_version == run.state_schema_version
    assert queued.status is AgentRunStatus.QUEUED

    native = AgentRunScheduler(store).enqueue(goal="Pin the native selection")
    assert native.engine == "native"
    assert native.graph_version == CURRENT_AGENT_GRAPH_VERSION


def test_known_old_graph_versions_can_be_selected_before_state_migration() -> None:
    from backend.agent_core.orchestration.graph_state import checkpoint_graph_version

    assert (
        checkpoint_graph_version(
            {"graph_version": LEGACY_AGENT_GRAPH_VERSION, "agent_state": {}}
        )
        == LEGACY_AGENT_GRAPH_VERSION
    )
    assert (
        checkpoint_graph_version(
            {
                "agent_state": {"graph_version": "reading-agent-ma03-v1"},
            }
        )
        == "reading-agent-ma03-v1"
    )
