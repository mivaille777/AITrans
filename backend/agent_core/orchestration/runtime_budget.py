from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from backend.agent_core.exceptions import AgentBudgetExceededError

_ACTIVE_BUDGET: ContextVar[Any | None] = ContextVar(
    "multi_agent_active_budget",
    default=None,
)


@contextmanager
def bind_runtime_budget(budget: Any) -> Iterator[None]:
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield
    finally:
        _ACTIVE_BUDGET.reset(token)


def reserve_runtime_resource(resource: str, amount: int = 1) -> None:
    budget = _ACTIVE_BUDGET.get()
    if budget is None:
        return
    if not bool(budget.reserve(resource, amount)):
        raise AgentBudgetExceededError(
            f"Multi-agent {resource} budget is exhausted."
        )


__all__ = ["bind_runtime_budget", "reserve_runtime_resource"]
