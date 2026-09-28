from __future__ import annotations

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.state import AgentState
from backend.agent_core.orchestration.agent_registry import build_default_agent_registry
from backend.api.agent_dependencies import get_agent_runtime
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.api.agent_runtime_jobs import get_agent_run_store
from backend.main import create_app
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_trace_store_service import AgentTraceStoreService
from fastapi.testclient import TestClient


class SnapshotRuntime:
    def checkpoint_orchestration_state(self, run_id: str) -> dict[str, object] | None:
        if run_id != "run-debug":
            return None
        return {
            "orchestration_route": {
                "lane": "workflow",
                "route_kind": "task_dag",
                "reason_code": "multi_task_request",
                "user_prompt": "PRIVATE_ROUTE_PROMPT",
            },
            "task_plan": {
                "plan_id": "plan-debug",
                "plan_revision": 3,
                "tasks": [
                    {
                        "task_id": "same-agent-doc-a",
                        "agent_id": "document",
                        "role": "document",
                        "depends_on": [],
                        "required": True,
                        "expected_output_kind": "document_analysis",
                        "objective": "PRIVATE_TASK_PROMPT",
                    },
                    {
                        "task_id": "same-agent-doc-b",
                        "agent_id": "document",
                        "role": "document",
                        "depends_on": ["same-agent-doc-a"],
                        "required": True,
                        "expected_output_kind": "document_analysis",
                        "objective": "PRIVATE_TASK_PROMPT_2",
                    },
                ],
            },
            "task_status_by_id": {"same-agent-doc-a": "partial"},
            "task_results": [
                {
                    "task_id": "same-agent-doc-a",
                    "attempt_ordinal": 2,
                    "status": "partial",
                    "error_code": "evidence_incomplete",
                    "usage": {"elapsed_ms": 42},
                    "artifact_refs": [
                        {
                            "artifact_id": "artifact-safe-id",
                            "version": 1,
                            "kind": "document_analysis",
                            "content_hash": "hash-safe",
                        }
                    ],
                    "content": {"body": "RAW_ARTIFACT_CONTENT"},
                }
            ],
            "artifact_refs": [
                {"artifact_id": "artifact-safe-id", "version": 1, "kind": "document_analysis", "content_hash": "hash-safe", "content": "RAW_ARTIFACT_CONTENT"}
            ],
        }


def _stores(tmp_path) -> tuple[AgentRunStore, AgentTraceStoreService]:
    run_store = AgentRunStore(storage_path=tmp_path / "agent_runtime.sqlite3")
    trace_store = AgentTraceStoreService(storage_path=tmp_path / "agent_observability.sqlite3")
    run_store.create_task_and_run(
        AgentTaskRecord(task_id="task-root", goal="Debug test task"),
        AgentRunRecord(
            task_id="task-root",
            run_id="run-debug",
            trace_id="trace-debug",
            runtime_profile=AgentRuntimeProfile.LONG_TASK,
        ),
    )
    run_store.transition_run(
        "run-debug",
        expected_status=AgentRunStatus.QUEUED,
        target_status=AgentRunStatus.RUNNING,
    )
    run_store.transition_run(
        "run-debug",
        expected_status=AgentRunStatus.RUNNING,
        target_status=AgentRunStatus.WAITING,
    )
    return run_store, trace_store


def test_catalog_exposes_public_agent_identity_only() -> None:
    response = TestClient(create_app()).get("/api/agent/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["agents"]) == 4
    assert all(
        set(agent) == {"agent_id", "name", "description", "capabilities", "version", "icon"}
        for agent in payload["agents"]
    )
    assert {agent["agent_id"] for agent in payload["agents"]} == {
        spec.agent_id for spec in build_default_agent_registry().list_agents()
    }
    assert "allowed_tools" not in response.text
    assert "graph_factory" not in response.text


def test_runtime_debug_returns_redacted_projection_and_stable_event_identity(tmp_path) -> None:
    run_store, trace_store = _stores(tmp_path)
    state = AgentState(task_id="task-root", run_id="run-debug", trace_id="trace-debug")
    events = [
        AgentEvent(
            event_type=AgentEventType.TASK_PLANNED,
            payload={"task_id": "same-agent-doc-a", "agent_id": "document", "role": "document", "depends_on": [], "required": True, "output_kind": "document_analysis", "attempt": 0, "objective": "PRIVATE_EVENT_PROMPT"},
            run_id="run-debug", trace_id="trace-debug", task_id="task-root", agent_id="document", agent_version="1", node_name="plan_task",
        ),
        AgentEvent(
            event_type=AgentEventType.TASK_PARTIAL,
            payload={"task_id": "same-agent-doc-a", "agent_id": "document", "status": "partial", "attempt": 2, "reason_code": "evidence_incomplete"},
            run_id="run-debug", trace_id="trace-debug", task_id="task-root", agent_id="document", agent_version="1", node_name="specialist",
        ),
        AgentEvent(
            event_type=AgentEventType.TOOL_CALL,
            payload={"name": "translate_selection", "arguments": {"api_key": "PRIVATE_API_KEY"}, "sandbox_id": "sandbox-safe-id"},
            run_id="run-debug", trace_id="trace-debug", task_id="task-root",
        ),
        AgentEvent(
            event_type=AgentEventType.RAG_QUERY_STARTED,
            payload={"query_id": "rag-safe-id", "query": "PRIVATE_RAG_QUERY"},
            run_id="run-debug", trace_id="trace-debug", task_id="task-root",
        ),
        AgentEvent(
            event_type=AgentEventType.WRITE_CONFIRMATION_REQUIRED,
            payload={"tool_name": "save_research_note", "arguments": {"body": "PRIVATE_TOOL_ARGS"}},
            run_id="run-debug", trace_id="trace-debug", task_id="task-root",
        ),
    ]
    for sequence, event in enumerate(events):
        event.sequence = sequence
        event.sequence = trace_store.append_event(state, event, sequence)
        persisted = run_store.append_event(event)
        assert persisted.sequence == event.sequence
        assert persisted.event_id == event.event_id

    app = create_app()
    app.dependency_overrides[get_agent_run_store] = lambda: run_store
    app.dependency_overrides[get_agent_trace_store_service] = lambda: trace_store
    app.dependency_overrides[get_agent_runtime] = lambda: SnapshotRuntime()
    client = TestClient(app)

    listing = client.get("/api/agent/runtime/debug/runs")
    response = client.get("/api/agent/runtime/debug/runs/run-debug")

    assert listing.status_code == response.status_code == 200
    payload = response.json()
    assert listing.json()[0]["status"] == "waiting"
    assert payload["status"] == "waiting"
    assert payload["route"] == {
        "lane": "workflow", "route_kind": "task_dag", "reason_code": "multi_task_request"
    }
    assert [item["task_id"] for item in payload["tasks"]] == [
        "same-agent-doc-a", "same-agent-doc-b"
    ]
    assert payload["tasks"][0]["agent_id"] == payload["tasks"][1]["agent_id"] == "document"
    assert payload["tasks"][0]["duration_ms"] == 42
    assert [attempt["attempt"] for attempt in payload["tasks"][0]["attempts"]] == [2]
    assert payload["tasks"][0]["artifact_refs"][0]["artifact_id"] == "artifact-safe-id"
    assert payload["tool_names"] == ["save_research_note", "translate_selection"]
    assert payload["related_ids"] == {
        "rag_query_ids": ["rag-safe-id"], "sandbox_ids": ["sandbox-safe-id"]
    }
    assert [item["sequence"] for item in payload["events"]] == list(range(len(events)))
    assert [item["event_id"] for item in payload["events"]] == [event.event_id for event in events]
    for secret in (
        "PRIVATE_ROUTE_PROMPT", "PRIVATE_TASK_PROMPT", "PRIVATE_TASK_PROMPT_2",
        "PRIVATE_EVENT_PROMPT", "PRIVATE_API_KEY", "PRIVATE_RAG_QUERY",
        "PRIVATE_TOOL_ARGS", "RAW_ARTIFACT_CONTENT", "objective", "arguments",
    ):
        assert secret not in response.text


def test_runtime_debug_returns_404_for_unknown_run(tmp_path) -> None:
    run_store = AgentRunStore(storage_path=tmp_path / "agent_runtime.sqlite3")
    trace_store = AgentTraceStoreService(storage_path=tmp_path / "agent_observability.sqlite3")
    app = create_app()
    app.dependency_overrides[get_agent_run_store] = lambda: run_store
    app.dependency_overrides[get_agent_trace_store_service] = lambda: trace_store
    app.dependency_overrides[get_agent_runtime] = lambda: SnapshotRuntime()

    response = TestClient(app).get("/api/agent/runtime/debug/runs/missing")

    assert response.status_code == 404
