from __future__ import annotations

from time import sleep

import pytest

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentDecisionTimeoutError,
    AgentToolTimeoutError,
)
from backend.agent_core.reliability import (
    AgentExecutionPolicy,
    AgentRunControl,
    run_react_decision_with_timeout,
    run_safe_tool_with_timeout,
)
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState


def test_agent_state_generates_run_and_trace_correlation_ids() -> None:
    first = AgentState(user_input="one")
    second = AgentState(user_input="two")

    assert first.run_id.startswith("run-")
    assert first.trace_id.startswith("trace-")
    assert first.run_id != second.run_id
    assert first.trace_id != second.trace_id


def test_run_control_rejects_exhausted_execution_budget() -> None:
    control = AgentRunControl(
        policy=AgentExecutionPolicy(total_timeout_seconds=0.01),
    )
    control.started_at -= 1.0

    with pytest.raises(AgentBudgetExceededError):
        control.checkpoint("planner")


def test_safe_tool_timeout_never_waits_for_blocking_compute_result() -> None:
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=1.0,
            tool_timeout_seconds=0.01,
            max_safe_retries=0,
        )
    )

    with pytest.raises(AgentToolTimeoutError):
        run_safe_tool_with_timeout(
            lambda: (sleep(0.1), "late")[1],
            control=control,
            tool_name="slow_compute",
        )


def test_react_decision_timeout_never_waits_for_blocking_model_result() -> None:
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=1.0,
            react_decision_timeout_seconds=0.01,
        )
    )

    with pytest.raises(AgentDecisionTimeoutError):
        run_react_decision_with_timeout(
            lambda: (sleep(0.1), "late decision")[1],
            control=control,
        )


def test_runtime_emits_structured_failure_with_correlation_ids() -> None:
    def fail_planner(_state: AgentState):
        raise RuntimeError("planner exploded")

    runtime = AgentRuntime(planner=fail_planner)
    state = AgentState(user_input="explain this")

    with pytest.raises(RuntimeError, match="planner exploded"):
        runtime.execute(state)

    assert [event.event_type for event in runtime.events] == [
        AgentEventType.AGENT_START,
        AgentEventType.CONTEXT_READY,
        AgentEventType.FAILURE,
        AgentEventType.AGENT_END,
    ]
    failure = runtime.events[-2]
    assert failure.run_id == state.run_id
    assert failure.trace_id == state.trace_id
    assert failure.payload["stage"] == "runtime"
    assert failure.payload["fallback_reason"] == "no_safe_fallback"
    assert runtime.events[-1].payload["status"] == "failed"


def test_runtime_cooperative_cancellation_emits_cancelled_terminal_state() -> None:
    control = AgentRunControl()
    control.cancel()
    runtime = AgentRuntime()
    state = AgentState(user_input="cancel me")

    with pytest.raises(AgentCancelledError):
        runtime.execute(state, control=control)

    assert [event.event_type for event in runtime.events] == [
        AgentEventType.CANCELLED,
        AgentEventType.AGENT_END,
    ]
    assert runtime.events[0].run_id == state.run_id
    assert runtime.events[0].payload["fallback_reason"] == "user_cancelled"
    assert runtime.events[-1].payload["status"] == "cancelled"


def test_event_sink_failure_does_not_break_agent_execution() -> None:
    runtime = AgentRuntime(
        planner=lambda _state: {"intent": "translate", "tool_name": "translate_selection"},
        tool_executor=lambda _state: {"translation": "ok"},
    )
    state = AgentState(user_input="hello")

    def broken_sink(_event) -> None:
        raise RuntimeError("stream closed")

    result = runtime.execute(state, event_sink=broken_sink)

    assert result.tool_results[-1]["translation"] == "ok"
    assert runtime.events[-1].event_type == AgentEventType.AGENT_END
    assert AgentEventType.FAILURE not in {event.event_type for event in runtime.events}
