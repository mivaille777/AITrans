from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.agent_core.orchestration.task_state import (
    InvalidTaskTransitionError,
    finish_attempt,
    prepare_retry,
    start_attempt,
    transition_task,
)
from backend.models.agent_tasks import TaskExecutionState, TaskStatus


T0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 16, 12, 1, tzinfo=UTC)
T2 = datetime(2026, 9, 16, 12, 2, tzinfo=UTC)
T3 = datetime(2026, 9, 16, 12, 3, tzinfo=UTC)


def test_attempt_history_is_append_only_across_explicit_retry() -> None:
    state = TaskExecutionState(task_id="doc-a")
    state = transition_task(state, TaskStatus.READY)
    state = start_attempt(state, attempt_id="attempt-1", started_at=T0)
    state = finish_attempt(
        state,
        status=TaskStatus.FAILED,
        error_code="provider_timeout",
        finished_at=T1,
    )

    assert state.status == TaskStatus.FAILED
    assert state.attempts[0].status == TaskStatus.FAILED
    assert state.attempts[0].error_code == "provider_timeout"

    state = prepare_retry(state)
    state = start_attempt(state, attempt_id="attempt-2", started_at=T2)
    state = finish_attempt(
        state,
        status=TaskStatus.SUCCEEDED,
        result_hash="result-hash",
        finished_at=T3,
    )

    assert state.status == TaskStatus.SUCCEEDED
    assert [item.attempt_id for item in state.attempts] == ["attempt-1", "attempt-2"]
    assert [item.ordinal for item in state.attempts] == [1, 2]
    assert state.attempts[0].status == TaskStatus.FAILED
    assert state.attempts[1].status == TaskStatus.SUCCEEDED


def test_terminal_success_cannot_silently_reenter_running() -> None:
    state = transition_task(TaskExecutionState(task_id="doc-a"), TaskStatus.READY)
    state = start_attempt(state, attempt_id="attempt-1", started_at=T0)
    state = finish_attempt(
        state,
        status=TaskStatus.SUCCEEDED,
        result_hash="ok",
        finished_at=T1,
    )

    with pytest.raises(InvalidTaskTransitionError):
        transition_task(state, TaskStatus.RUNNING)

    with pytest.raises(InvalidTaskTransitionError):
        prepare_retry(state)


def test_new_attempt_requires_ready_and_unique_attempt_id() -> None:
    state = TaskExecutionState(task_id="doc-a")
    with pytest.raises(InvalidTaskTransitionError):
        start_attempt(state, attempt_id="attempt-1", started_at=T0)

    state = transition_task(state, TaskStatus.READY)
    state = start_attempt(state, attempt_id="attempt-1", started_at=T0)
    state = finish_attempt(
        state,
        status=TaskStatus.FAILED,
        finished_at=T1,
    )
    state = prepare_retry(state)

    with pytest.raises(ValueError, match="already exists"):
        start_attempt(state, attempt_id="attempt-1", started_at=T2)


def test_blocked_and_skipped_are_explicit_non_success_terminal_states() -> None:
    blocked = transition_task(
        TaskExecutionState(task_id="blocked"),
        TaskStatus.BLOCKED,
    )
    skipped = transition_task(
        TaskExecutionState(task_id="skipped"),
        TaskStatus.SKIPPED,
    )

    assert blocked.status == TaskStatus.BLOCKED
    assert skipped.status == TaskStatus.SKIPPED
