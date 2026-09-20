from __future__ import annotations

from threading import Barrier, Lock
from time import sleep

from backend.agent_core.orchestration.parallel_executor import ParallelTaskGraphExecutor
from backend.models.agent_tasks import TaskRole, TaskStatus
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope, success


def test_independent_tasks_enter_specialists_concurrently() -> None:
    barrier = Barrier(2, timeout=2)
    lock = Lock()
    active = 0
    maximum = 0

    def execute(task):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait()
        with lock:
            active -= 1
        return success(task.task_id)

    probe = FunctionExecutor(execute)
    result = ParallelTaskGraphExecutor({TaskRole.DOCUMENT: probe}).execute(
        plan=plan(),
        scope=scope(),
        run_id="parallel-run",
    )

    assert maximum == 2
    assert {item.task_id for item in result.results} == {"a", "b"}


def test_dependent_task_waits_for_its_parent_result() -> None:
    observed: list[tuple[str, tuple[str, ...]]] = []

    class DependencyProbe(FunctionExecutor):
        def execute(self, *, task, scope, dependency_results, memory_snapshot):
            del scope, memory_snapshot
            observed.append((task.task_id, tuple(sorted(dependency_results))))
            return success(task.task_id)

    probe = DependencyProbe(lambda task: success(task.task_id))
    ParallelTaskGraphExecutor({TaskRole.DOCUMENT: probe}).execute(
        plan=plan(dependencies={"b": ["a"]}),
        scope=scope(),
        run_id="dependency-run",
    )

    assert observed == [("a", ()), ("b", ("a",))]


def test_gpu_marked_tasks_share_one_process_slot() -> None:
    lock = Lock()
    active = 0
    maximum = 0

    def execute(task):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        sleep(0.05)
        with lock:
            active -= 1
        return success(task.task_id)

    task_plan = plan()
    task_plan = task_plan.model_copy(
        update={
            "tasks": [
                item.model_copy(update={"allowed_tools": ["analyze_image_gpu"]})
                for item in task_plan.tasks
            ]
        }
    )
    ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: FunctionExecutor(execute)}
    ).execute(plan=task_plan, scope=scope(), run_id="gpu-run")

    assert maximum == 1


def test_failure_blocks_only_its_dependents_and_preserves_other_results() -> None:
    def execute(task):
        if task.task_id == "b":
            raise RuntimeError("synthetic failure")
        return success(task.task_id)

    task_plan = plan(
        ("a", "b", "c", "d"),
        dependencies={"c": ["a"], "d": ["b"]},
    )
    result = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: FunctionExecutor(execute)}
    ).execute(plan=task_plan, scope=scope(), run_id="partial-run")

    statuses = {item.task_id: item.status for item in result.results}
    assert statuses == {
        "a": TaskStatus.SUCCEEDED,
        "b": TaskStatus.FAILED,
        "c": TaskStatus.SUCCEEDED,
        "d": TaskStatus.BLOCKED,
    }
