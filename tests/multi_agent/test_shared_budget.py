from __future__ import annotations

from time import sleep

import pytest

from backend.agent_core.exceptions import AgentBudgetExceededError
from backend.agent_core.multi_agent.trace import MultiAgentTraceCollector
from backend.agent_core.orchestration.parallel_executor import (
    ParallelExecutionPolicy,
    ParallelTaskGraphExecutor,
    SharedRunBudget,
)
from backend.agent_core.orchestration.runtime_budget import (
    bind_runtime_budget,
    reserve_runtime_resource,
)
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.models.agent_tasks import ResourceUsage, TaskRole, TaskStatus
from tests.multi_agent.scheduler_support import FunctionExecutor, plan, scope, success


def test_budget_reservations_are_atomic() -> None:
    budget = SharedRunBudget(ParallelExecutionPolicy(max_model_calls=1))
    assert budget.reserve("model_calls")
    assert not budget.reserve("model_calls")
    budget.record(ResourceUsage(model_calls=1, tool_calls=2))
    assert budget.usage.model_calls == 1
    assert budget.usage.tool_calls == 2


def test_specialist_resource_call_must_reserve_before_execution() -> None:
    budget = SharedRunBudget(ParallelExecutionPolicy(max_retrievals=1))
    with bind_runtime_budget(budget):
        reserve_runtime_resource("retrievals")
        with pytest.raises(AgentBudgetExceededError):
            reserve_runtime_resource("retrievals")


def test_exhausted_budget_blocks_new_dispatch_and_emits_event() -> None:
    probe = FunctionExecutor(lambda task: success(task.task_id))
    collector = MultiAgentTraceCollector(run_id="budget-run")
    result = ParallelTaskGraphExecutor(
        {TaskRole.DOCUMENT: probe},
        policy=ParallelExecutionPolicy(max_model_calls=1),
    ).execute(
        plan=plan(),
        scope=scope(),
        run_id="budget-run",
        collector=collector,
    )

    assert probe.calls == ["a"]
    statuses = {item.task_id: item.status for item in result.results}
    assert statuses == {"a": TaskStatus.SUCCEEDED, "b": TaskStatus.BLOCKED}
    assert any(item.event_type == "budget_exhausted" for item in collector.events)


def test_total_deadline_stops_dispatching_new_tasks() -> None:
    def delayed(task):
        sleep(0.05)
        return success(task.task_id)

    probe = FunctionExecutor(delayed)
    control = AgentRunControl(
        policy=AgentExecutionPolicy(total_timeout_seconds=0.01)
    )
    with pytest.raises(AgentBudgetExceededError):
        ParallelTaskGraphExecutor(
            {TaskRole.DOCUMENT: probe},
            policy=ParallelExecutionPolicy(max_parallel_experts=1),
        ).execute(
            plan=plan(dependencies={"b": ["a"]}),
            scope=scope(),
            run_id="deadline-run",
            control=control,
        )

    assert probe.calls == ["a"]
