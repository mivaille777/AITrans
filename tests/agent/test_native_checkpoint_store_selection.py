from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.api import agent_dependencies


class _CheckpointService:
    storage_path = Path("unused-checkpoint-database.sqlite3")
    checkpointer = InMemorySaver()


class _MemoryCoordinator:
    def policy_revision(self, _profile_id):
        return "memory-policy:test"

    def load_snapshot(self, **_kwargs):
        return {"status": "empty", "snapshot_id": ""}


@pytest.mark.parametrize(
    ("engine", "legacy_checkpoint_expected"),
    [("native", False), ("compat", True)],
)
def test_only_legacy_engine_constructs_task_checkpoint_store(
    monkeypatch, engine, legacy_checkpoint_expected
) -> None:
    created: list[object] = []

    class _TaskCheckpointStore:
        def __init__(self, path):
            self.path = path
            created.append(self)

    monkeypatch.setattr(
        agent_dependencies,
        "SQLiteTaskCheckpointStore",
        _TaskCheckpointStore,
    )
    monkeypatch.setattr(
        agent_dependencies,
        "build_artifact_store",
        lambda **_kwargs: InMemoryArtifactStore(),
    )
    monkeypatch.setattr(
        agent_dependencies,
        "get_memory_coordinator",
        lambda: _MemoryCoordinator(),
    )
    monkeypatch.setattr(
        agent_dependencies,
        "get_llm_gateway",
        lambda: SimpleNamespace(create_text_service=lambda *_args: object()),
    )

    runtime = agent_dependencies.get_agent_runtime(
        service=SimpleNamespace(tool_registry=None),
        resolver=object(),
        checkpoint_service=_CheckpointService(),
        graph_engine=engine,
    )
    try:
        executor = runtime.workflow_adapter._orchestration_service.executor
        assert (executor.checkpoints is not None) is legacy_checkpoint_expected
        assert bool(created) is legacy_checkpoint_expected
    finally:
        runtime.workflow_adapter.close()
