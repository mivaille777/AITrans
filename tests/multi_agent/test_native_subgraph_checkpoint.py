from __future__ import annotations

from hashlib import sha256
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from backend.agent_core.orchestration.agent_registry import AgentSpec
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.orchestration.specialist_adapter import (
    create_specialist_node,
    resolve_per_invocation_graph,
    specialist_memory_snapshot,
)
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_artifacts import ArtifactKind, DocumentAnalysisArtifact
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus
from backend.services.agent_checkpoint_service import AgentCheckpointService


class _SpecialistState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    result: TaskResult


class _RootState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    task_results: list[dict[str, Any]]
    task_status_by_id: dict[str, str]
    artifact_refs: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]


class _RuntimeContext(TypedDict, total=False):
    memory_snapshot: dict[str, Any]
    persistent_checkpoints: bool
    control: AgentRunControl


def _task(task_id: str, scope: ScopeContext) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        agent_id="checkpoint-test",
        objective=f"Analyze {task_id}",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope.scope_ref,
        allowed_tools=[],
    )


def test_per_invocation_specialist_uses_shared_sqlite_namespace_per_task_and_omits_memory(
    tmp_path,
) -> None:
    observed: list[dict[str, Any]] = []

    def work(state: _SpecialistState, runtime: Runtime[_RuntimeContext]):
        memory = specialist_memory_snapshot(runtime, state)
        observed.append(dict(memory))
        return {
            "result": TaskResult(
                task_id=state["task"].task_id,
                status=TaskStatus.SUCCEEDED,
            )
        }

    child_builder = StateGraph(_SpecialistState, context_schema=_RuntimeContext)
    child_builder.add_node("work", work)
    child_builder.add_edge(START, "work")
    child_builder.add_edge("work", END)
    standalone_graph = child_builder.compile()
    checkpointed_graph = resolve_per_invocation_graph(
        "checkpoint-test", standalone_graph
    )
    assert standalone_graph.checkpointer is None
    assert checkpointed_graph.checkpointer is True

    spec = AgentSpec(
        agent_id="checkpoint-test",
        version="test-v1",
        display_name="Checkpoint Test",
        description="A minimal checkpointed specialist.",
        capabilities=frozenset({"test"}),
        accepted_input_kinds=frozenset(),
        output_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
        allowed_tools=frozenset(),
        default_tools=(),
        default_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
    )
    node = create_specialist_node(
        spec, standalone_graph, checkpointed_graph=checkpointed_graph
    )
    scope = ScopeContext.issue(
        profile_id="profile-checkpoint-test",
        scope_revision="checkpoint-test-v1",
        allowed_document_ids=["paper-a"],
    )
    checkpoint_service = AgentCheckpointService(
        storage_path=tmp_path / "agent-checkpoints.sqlite3"
    )
    try:
        root_builder = StateGraph(_RootState, context_schema=_RuntimeContext)
        root_builder.add_node("dispatch", node)
        root_builder.add_edge(START, "dispatch")
        root_builder.add_edge("dispatch", END)
        root = root_builder.compile(checkpointer=checkpoint_service.checkpointer)
        memory = {"snapshot_id": "snapshot-7", "private": "opaque-memory-body"}
        for task_id in ("task-a", "task-b"):
            result = root.invoke(
                {
                    "task": _task(task_id, scope),
                    "scope": scope,
                    "dependency_results": {},
                },
                {"configurable": {"thread_id": "native-subgraph-run"}},
                context={
                    "memory_snapshot": memory,
                    "persistent_checkpoints": True,
                    "control": AgentRunControl(),
                },
            )
            assert TaskResult.model_validate(result["task_results"][0]).task_id == task_id

        assert observed == [memory, memory]
        checkpoints = list(
            checkpoint_service.checkpointer.list(
                {"configurable": {"thread_id": "native-subgraph-run"}},
                limit=100,
            )
        )
        subgraph_checkpoints = [
            item
            for item in checkpoints
            if "task_" in item.config["configurable"].get("checkpoint_ns", "")
        ]
        assert subgraph_checkpoints
        task_namespaces = {
            item.config["configurable"]["checkpoint_ns"]
            for item in subgraph_checkpoints
        }
        assert len(task_namespaces) == 2
        assert task_namespaces == {
            f"dispatch|task_{sha256(task_id.encode('utf-8')).hexdigest()[:16]}"
            for task_id in ("task-a", "task-b")
        }
        for item in subgraph_checkpoints:
            channels = item.checkpoint.get("channel_values", {})
            assert "memory_snapshot" not in channels
            assert "opaque-memory-body" not in repr(channels)
    finally:
        checkpoint_service.close()


def test_temporary_specialist_uses_ephemeral_artifacts_and_no_durable_subgraph(
    tmp_path,
) -> None:
    scope = ScopeContext.issue(
        profile_id="profile-temporary-checkpoint-test",
        scope_revision="temporary-checkpoint-test-v1",
        allowed_document_ids=["paper-a"],
    )
    durable_artifacts = InMemoryArtifactStore()
    temporary_artifacts = InMemoryArtifactStore()

    def build(artifact_store: InMemoryArtifactStore):
        def work(state: _SpecialistState):
            task = TaskSpec.model_validate(state["task"])
            artifact = artifact_store.put(
                DocumentAnalysisArtifact(
                    artifact_id=f"artifact:{task.task_id}",
                    producer_task_id=task.task_id,
                    scope_ref=scope.scope_ref,
                    document_id="paper-a",
                )
            )
            return {
                "result": TaskResult(
                    task_id=task.task_id,
                    attempt_id=f"{task.task_id}:1",
                    status=TaskStatus.SUCCEEDED,
                    artifact_refs=[artifact.ref()],
                )
            }

        builder = StateGraph(_SpecialistState)
        builder.add_node("work", work)
        builder.add_edge(START, "work")
        builder.add_edge("work", END)
        return builder.compile()

    persistent_graph = build(durable_artifacts)
    temporary_graph = build(temporary_artifacts)
    checkpointed_graph = resolve_per_invocation_graph(
        "checkpoint-test", persistent_graph
    )
    spec = AgentSpec(
        agent_id="checkpoint-test",
        version="test-v1",
        display_name="Checkpoint Test",
        description="A temporary specialist must use its ephemeral artifact store.",
        capabilities=frozenset({"test"}),
        accepted_input_kinds=frozenset(),
        output_kinds=frozenset({ArtifactKind.DOCUMENT_ANALYSIS}),
        allowed_tools=frozenset(),
        default_tools=(),
        default_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
    )
    node = create_specialist_node(
        spec,
        persistent_graph,
        checkpointed_graph=checkpointed_graph,
        temporary_graph=temporary_graph,
    )
    root_builder = StateGraph(_RootState, context_schema=_RuntimeContext)
    root_builder.add_node("dispatch", node)
    root_builder.add_edge(START, "dispatch")
    root_builder.add_edge("dispatch", END)
    root = root_builder.compile()
    result = root.invoke(
        {
            "task": _task("temporary-task", scope),
            "scope": scope,
            "dependency_results": {},
        },
        context={
            "memory_snapshot": {"snapshot_id": "temporary-memory"},
            "persistent_checkpoints": False,
            "temporary": True,
            "control": AgentRunControl(),
        },
    )

    task_result = TaskResult.model_validate(result["task_results"][0])
    assert task_result.status is TaskStatus.SUCCEEDED, task_result.error_code
    assert durable_artifacts.get("artifact:temporary-task", 1) is None
    assert temporary_artifacts.get("artifact:temporary-task", 1) is not None
