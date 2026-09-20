from __future__ import annotations

from threading import Event, Thread
from time import monotonic, sleep

from backend.agent_core.exceptions import AgentCancelledError
from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_core.orchestration.parallel_executor import (
    ParallelTaskGraphExecutor,
    SQLiteTaskCheckpointStore,
)
from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_artifacts import DocumentAnalysisArtifact
from backend.models.agent_tasks import TaskResult, TaskRole, TaskStatus
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope


def test_cancelled_attempt_cannot_publish_a_late_artifact(tmp_path) -> None:
    store = InMemoryArtifactStore()
    entered = Event()
    release = Event()
    active_scope = scope()

    def delayed(task):
        entered.set()
        assert release.wait(2)
        artifact = store.put(
            DocumentAnalysisArtifact(
                artifact_id="late-artifact",
                producer_task_id=task.task_id,
                scope_ref=active_scope.scope_ref,
                document_id="paper-a",
            )
        )
        return SpecialistExecution(
            result=TaskResult(
                task_id=task.task_id,
                attempt_id=f"{task.task_id}:1",
                status=TaskStatus.SUCCEEDED,
                artifact_refs=[artifact.ref()],
            )
        )

    control = AgentRunControl()
    collector = MultiAgentTraceCollector(run_id="cancel-run")
    checkpoints = SQLiteTaskCheckpointStore(tmp_path / "cancel.sqlite3")
    executor = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: FunctionExecutor(delayed)},
        checkpoint_store=checkpoints,
        artifact_store=store,
    )
    task_plan = plan(("a",))
    plan_hash = executor._plan_hash(task_plan)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            executor.execute(
                plan=task_plan,
                scope=active_scope,
                run_id="cancel-run",
                collector=collector,
                control=control,
            )
        except AgentCancelledError as exc:
            errors.append(exc)

    worker = Thread(target=run)
    worker.start()
    assert entered.wait(2)
    control.cancel()
    worker.join(2)
    assert errors and isinstance(errors[0], AgentCancelledError)
    assert not checkpoints.acquire_lease(
        run_id="cancel-run",
        plan_hash=plan_hash,
        owner_id="second-window",
        lease_seconds=30,
    )

    release.set()
    deadline = monotonic() + 2
    while store.get("late-artifact", 1) is not None and monotonic() < deadline:
        sleep(0.01)
    assert store.get("late-artifact", 1) is None
    assert not any(item.event_type == "task_completed" for item in collector.events)
    while monotonic() < deadline:
        if checkpoints.acquire_lease(
            run_id="cancel-run",
            plan_hash=plan_hash,
            owner_id="second-window",
            lease_seconds=30,
        ):
            break
        sleep(0.01)
    else:
        raise AssertionError("late worker did not release the run lease")
