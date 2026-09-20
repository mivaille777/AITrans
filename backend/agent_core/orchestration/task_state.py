from __future__ import annotations

from datetime import datetime

from backend.models.agent_tasks import (
    TERMINAL_TASK_STATUSES,
    TaskAttemptRecord,
    TaskExecutionState,
    TaskStatus,
    utc_now,
)


class InvalidTaskTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {
            TaskStatus.READY,
            TaskStatus.BLOCKED,
            TaskStatus.SKIPPED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.READY: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.SKIPPED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_CONFIRMATION,
            TaskStatus.SUCCEEDED,
            TaskStatus.PARTIAL,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_CONFIRMATION: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
}


def transition_task(
    state: TaskExecutionState,
    target: TaskStatus,
) -> TaskExecutionState:
    if state.status == target:
        return state.model_copy(deep=True)
    allowed = _ALLOWED_TRANSITIONS.get(state.status, frozenset())
    if target not in allowed:
        raise InvalidTaskTransitionError(
            f"invalid task transition: {state.status.value} -> {target.value}"
        )
    return state.model_copy(update={"status": target}, deep=True)


def start_attempt(
    state: TaskExecutionState,
    *,
    attempt_id: str,
    started_at: datetime | None = None,
) -> TaskExecutionState:
    if state.status != TaskStatus.READY:
        raise InvalidTaskTransitionError("a new attempt may start only from ready")
    normalized = str(attempt_id or "").strip()
    if not normalized:
        raise ValueError("attempt_id is required")
    if any(item.attempt_id == normalized for item in state.attempts):
        raise ValueError(f"attempt_id already exists: {normalized}")

    attempt = TaskAttemptRecord(
        task_id=state.task_id,
        attempt_id=normalized,
        ordinal=len(state.attempts) + 1,
        status=TaskStatus.RUNNING,
        started_at=started_at or utc_now(),
    )
    return state.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "attempts": [*state.attempts, attempt],
            "current_attempt_id": normalized,
        },
        deep=True,
    )


def finish_attempt(
    state: TaskExecutionState,
    *,
    status: TaskStatus,
    result_hash: str = "",
    error_code: str = "",
    finished_at: datetime | None = None,
) -> TaskExecutionState:
    if state.status not in {TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION}:
        raise InvalidTaskTransitionError("no running attempt is available to finish")
    if status not in {
        TaskStatus.SUCCEEDED,
        TaskStatus.PARTIAL,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }:
        raise InvalidTaskTransitionError(
            f"attempt cannot finish with status {status.value}"
        )
    if not state.current_attempt_id:
        raise InvalidTaskTransitionError("current_attempt_id is missing")

    updated: list[TaskAttemptRecord] = []
    found = False
    for item in state.attempts:
        if item.attempt_id == state.current_attempt_id:
            found = True
            updated.append(
                item.model_copy(
                    update={
                        "status": status,
                        "finished_at": finished_at or utc_now(),
                        "result_hash": str(result_hash or ""),
                        "error_code": str(error_code or ""),
                    }
                )
            )
        else:
            updated.append(item)
    if not found:
        raise InvalidTaskTransitionError("current attempt record is missing")

    return state.model_copy(
        update={
            "status": status,
            "attempts": updated,
            "current_attempt_id": "",
        },
        deep=True,
    )


def prepare_retry(state: TaskExecutionState) -> TaskExecutionState:
    if state.status not in {
        TaskStatus.FAILED,
        TaskStatus.PARTIAL,
        TaskStatus.CANCELLED,
    }:
        raise InvalidTaskTransitionError(
            "retry requires an explicitly retryable terminal result"
        )
    return state.model_copy(
        update={"status": TaskStatus.READY, "current_attempt_id": ""},
        deep=True,
    )


def is_terminal(state: TaskExecutionState) -> bool:
    return state.status in TERMINAL_TASK_STATUSES


__all__ = [
    "InvalidTaskTransitionError",
    "finish_attempt",
    "is_terminal",
    "prepare_retry",
    "start_attempt",
    "transition_task",
]
