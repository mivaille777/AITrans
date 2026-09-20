from __future__ import annotations

from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector
from backend.agent_core.orchestration.parallel_executor import (
    ParallelTaskGraphExecutor,
    SQLiteTaskCheckpointStore,
)
from backend.models.agent_tasks import TaskRole
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope, success


def test_resume_reuses_completed_task_and_retries_only_interrupted_task(tmp_path) -> None:
    store = SQLiteTaskCheckpointStore(tmp_path / "agent-checkpoints.sqlite3")
    task_plan = plan()
    seed = ParallelTaskGraphExecutor({})
    plan_hash = seed._plan_hash(task_plan)
    assert store.acquire_lease(
        run_id="resume-run",
        plan_hash=plan_hash,
        owner_id="crashed-owner",
        lease_seconds=30,
    )
    store.begin_task(run_id="resume-run", task_id="a", plan_hash=plan_hash, attempt_ordinal=1)
    store.complete_task(run_id="resume-run", plan_hash=plan_hash, execution=success("a"))
    store.begin_task(run_id="resume-run", task_id="b", plan_hash=plan_hash, attempt_ordinal=1)
    store.release_lease("resume-run", "crashed-owner")

    probe = FunctionExecutor(lambda task: success(task.task_id))
    collector = MultiAgentTraceCollector(run_id="resume-run")
    result = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: probe},
        checkpoint_store=store,
    ).execute(
        plan=task_plan,
        scope=scope(),
        run_id="resume-run",
        collector=collector,
    )

    assert probe.calls == ["b"]
    assert {item.task_id: item.attempt_ordinal for item in result.results} == {"a": 1, "b": 2}
    event_types = [item.event_type for item in collector.events]
    assert "workflow_resumed" in event_types
    assert "task_retrying" in event_types
