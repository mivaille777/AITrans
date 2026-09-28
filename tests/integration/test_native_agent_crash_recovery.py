from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from backend.agent_core.orchestration.agent_registry import AgentRegistry, AgentSpec
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.orchestration.parallel_executor import ParallelExecutionPolicy
from backend.agent_core.orchestration.planner import ValidatedSupervisorPlanner
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import CURRENT_AGENT_GRAPH_VERSION, AgentState
from backend.agent_graph.root_agent_graph import RootAgentGraph
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tasks import (
    ScopeContext,
    TaskInputRef,
    TaskResult,
    TaskSpec,
    TaskStatus,
)
from backend.models.agent_tools import AgentPlan
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge
from backend.services.research_orchestration_service import ResearchOrchestrationService


class _SpecialistState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    result: TaskResult


class _NeverExecutor:
    policy = ParallelExecutionPolicy()

    def execute(self, **_kwargs):
        raise AssertionError("native recovery must not enter the legacy executor")


class _Router:
    def route(self, *_args, **_kwargs):
        return OrchestrationRoute(
            lane=OrchestrationLane.WORKFLOW,
            reason_code="native-process-recovery",
        )


class _ScopeResolver:
    def resolve(self, *, profile_id="", memory_policy_revision="", **_kwargs):
        return ScopeContext.issue(
            profile_id=profile_id,
            scope_revision="native-process-recovery-v1",
            memory_policy_revision=memory_policy_revision,
            allowed_document_ids=["paper-1", "paper-2", "paper-3"],
        )


class _Memory:
    def policy_revision(self, _profile_id):
        return "memory-policy:native-process-recovery-v1"

    def load_snapshot(self, *, profile_id, scope, run_id="", **_kwargs):
        return {
            "status": "ready",
            "snapshot_id": f"memory:{run_id}",
            "profile_id": profile_id,
            "scope_ref": scope.scope_ref,
            "policy_revision": scope.memory_policy_revision,
            "role_projections": {},
        }

    def submit_candidates(self, **_kwargs):
        return None


class _Product:
    def resolve_route(self, **_payload):
        return (
            AgentRouteDecision(kind="answer", source="deterministic", intent="answer"),
            {"duration_ms": 0, "llm_called": False},
        )

    def run(self, **payload):
        return type(
            "ProductResult",
            (),
            {
                "status": "completed",
                "plan": AgentPlan(action="answer", user_visible_reason="done"),
                "output_text": "done",
                "provider": "test",
                "model": "test",
                "request_id": payload.get("request_id", 0),
                "tool_result": None,
                "route": AgentRouteDecision.model_validate(
                    payload["_resolved_route"]
                ),
            },
        )()


def _record(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(value + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _build_graph(checkpointer, *, mode: str, journal_path: Path) -> RootAgentGraph:
    def execute(state: _SpecialistState, runtime: Runtime[Any]):
        task = state["task"]
        _record(journal_path, f"started:{task.task_id}")
        if mode == "crash" and task.task_id == "document-3":
            os._exit(73)
        if mode == "cancel" and task.task_id == "document-1":
            control = (runtime.context or {}).get("control")
            if control is not None:
                control.cancel()
        result = TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED,
        )
        _record(journal_path, f"completed:{task.task_id}")
        return {"result": result}

    def compiled(agent_id: str):
        builder = StateGraph(_SpecialistState)
        builder.add_node(f"run_{agent_id}", execute)
        builder.add_edge(START, f"run_{agent_id}")
        builder.add_edge(f"run_{agent_id}", END)
        return builder.compile()

    document_kind = ArtifactKind.DOCUMENT_ANALYSIS
    comparison_kind = ArtifactKind.COMPARISON
    registry = AgentRegistry(
        (
            AgentSpec(
                agent_id="document",
                version="test-v1",
                display_name="Document Analyst",
                description="Process-boundary recovery fixture.",
                capabilities=frozenset({"document_analysis"}),
                accepted_input_kinds=frozenset({document_kind}),
                output_kinds=frozenset({document_kind}),
                allowed_tools=frozenset(),
                default_tools=(),
                default_output_kind=document_kind,
                graph_factory=lambda: compiled("document"),
            ),
            AgentSpec(
                agent_id="research",
                version="test-v1",
                display_name="Research Synthesizer",
                description="Wait for all document tasks.",
                capabilities=frozenset({"research_synthesis"}),
                accepted_input_kinds=frozenset({document_kind}),
                output_kinds=frozenset({comparison_kind}),
                allowed_tools=frozenset(),
                default_tools=(),
                default_output_kind=comparison_kind,
                graph_factory=lambda: compiled("research"),
            ),
        )
    )

    def plan_provider(*, scope_ref, plan_revision, **_kwargs):
        definitions = (
            ("document-1", "document", ()),
            ("document-2", "document", ()),
            ("document-3", "document", ("document-1", "document-2")),
            ("research", "research", ("document-3",)),
        )
        tasks = []
        for task_id, agent_id, dependencies in definitions:
            inputs = [
                TaskInputRef(
                    artifact_id=f"artifact:{dependency}",
                    version=1,
                    kind=document_kind,
                    producer_task_id=dependency,
                )
                for dependency in dependencies
            ]
            expected_kind = (
                comparison_kind if agent_id == "research" else document_kind
            )
            tasks.append(
                TaskSpec(
                    task_id=task_id,
                    agent_id=agent_id,
                    objective=f"Process {task_id}",
                    depends_on=list(dependencies),
                    input_refs=inputs,
                    required=True,
                    expected_output_kind=expected_kind,
                    scope_ref=scope_ref,
                    allowed_tools=[],
                    plan_revision=plan_revision,
                )
            )
        return {
            "plan_id": f"process-plan-{plan_revision}",
            "plan_revision": plan_revision,
            "scope_ref": scope_ref,
            "tasks": [task.model_dump(mode="json") for task in tasks],
        }

    service = ResearchOrchestrationService(
        scope_resolver=_ScopeResolver(),
        executor=_NeverExecutor(),
        router=_Router(),
        planner=ValidatedSupervisorPlanner(
            agent_registry=registry,
            provider=plan_provider,
        ),
        memory_port=_Memory(),
        artifact_store=InMemoryArtifactStore(),
    )
    return RootAgentGraph(
        ProductAgentRuntimeAdapter(_Product()),
        checkpointer=checkpointer,
        orchestration_service=service,
        collaboration_adapter=MultiAgentRuntimeBridge(orchestrator=service),
        graph_version=CURRENT_AGENT_GRAPH_VERSION,
        engine="native",
    )


def _state(run_id: str) -> AgentState:
    return AgentState(
        run_id=run_id,
        task_id=f"task-{run_id}",
        trace_id=f"trace-{run_id}",
        user_input="Analyze three documents and synthesize the result.",
        browser_context={
            "profile_id": "profile-process-recovery",
            "knowledge_document_ids": ["paper-1", "paper-2", "paper-3"],
            "multi_agent_mode": "force",
        },
    )


def _process_main(mode: str, checkpoint_path: str, journal_path: str, run_id: str) -> None:
    service = AgentCheckpointService(storage_path=checkpoint_path)
    try:
        graph = _build_graph(service.checkpointer, mode=mode, journal_path=Path(journal_path))
        if mode == "recover":
            state = graph.checkpoint_state(run_id)
            if state is None:
                raise RuntimeError("the interrupted run has no Root checkpoint")
            result = graph.resume_with_events(state, lambda *_args: None)
            print(
                "RECOVERED "
                + json.dumps(
                    {
                        "run_id": result.run_id,
                        "status": result.orchestration_status,
                        "tasks": sorted(
                            item["task_id"] for item in result.orchestration_results
                        ),
                        "results": [
                            {
                                "task_id": item["task_id"],
                                "status": item["status"],
                                "error_code": item.get("error_code", ""),
                            }
                            for item in result.orchestration_results
                        ],
                    }
                ),
                flush=True,
            )
        else:
            graph.run_with_events(_state(run_id), lambda *_args: None)
    finally:
        service.close()


def _run_child(mode: str, database: Path, journal: Path, run_id: str):
    worker_file = Path(__file__).resolve()
    source = (
        "import importlib.util,sys; "
        "spec=importlib.util.spec_from_file_location('native_crash_worker',sys.argv[1]); "
        "module=importlib.util.module_from_spec(spec); "
        "sys.modules[spec.name]=module; spec.loader.exec_module(module); "
        "module._process_main(*sys.argv[2:])"
    )
    return subprocess.run(
        [sys.executable, "-c", source, str(worker_file), mode, str(database), str(journal), run_id],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


def test_native_root_recovers_only_interrupted_specialist_in_a_new_process(tmp_path) -> None:
    database = tmp_path / "agent-checkpoints.sqlite3"
    journal = tmp_path / "specialist-events.jsonl"
    run_id = "native-process-boundary-run"

    first = _run_child("crash", database, journal, run_id)
    assert first.returncode == 73, first.stdout + first.stderr
    first_events = journal.read_text(encoding="utf-8").splitlines()
    assert "completed:document-1" in first_events
    assert "completed:document-2" in first_events
    assert "started:document-3" in first_events
    assert not any(item.startswith("started:research") for item in first_events)

    recovered = _run_child("recover", database, journal, run_id)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    summary_line = next(
        line for line in recovered.stdout.splitlines() if line.startswith("RECOVERED ")
    )
    summary = json.loads(summary_line.removeprefix("RECOVERED "))
    assert summary["run_id"] == run_id
    assert set(summary["tasks"]) == {"document-1", "document-2", "document-3", "research"}

    events = journal.read_text(encoding="utf-8").splitlines()
    starts = [item.removeprefix("started:") for item in events if item.startswith("started:")]
    assert starts.count("document-1") == 1
    assert starts.count("document-2") == 1
    assert starts.count("document-3") == 2
    assert starts.count("research") == 1


def test_native_cancelled_specialist_resumes_from_its_subgraph_checkpoint(tmp_path) -> None:
    database = tmp_path / "agent-checkpoints.sqlite3"
    journal = tmp_path / "specialist-events.jsonl"
    run_id = "native-cancel-resume-run"
    checkpoint_service = AgentCheckpointService(storage_path=database)
    try:
        graph = _build_graph(
            checkpoint_service.checkpointer,
            mode="cancel",
            journal_path=journal,
        )
        import pytest

        from backend.agent_core.exceptions import AgentCancelledError

        with pytest.raises(AgentCancelledError):
            graph.run_with_events(
                _state(run_id), lambda *_args: None, control=AgentRunControl()
            )

        resumed_graph = _build_graph(
            checkpoint_service.checkpointer,
            mode="resume",
            journal_path=journal,
        )
        checkpointed = resumed_graph.checkpoint_state(run_id)
        assert checkpointed is not None
        result = resumed_graph.resume_with_events(
            checkpointed, lambda *_args: None, control=AgentRunControl()
        )
        assert result.orchestration_status == "completed"
        events = journal.read_text(encoding="utf-8").splitlines()
        starts = [item.removeprefix("started:") for item in events if item.startswith("started:")]
        assert starts.count("document-1") == 1
    finally:
        checkpoint_service.close()
