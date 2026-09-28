from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from threading import BoundedSemaphore, RLock
from typing import Any

from backend.models.agent_tasks import ResourceUsage

GLOBAL_EXPERT_SLOTS = BoundedSemaphore(2)
GLOBAL_GPU_SLOTS = BoundedSemaphore(1)


def _optional_sum(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return int(left or 0) + int(right or 0)


class SharedRunBudget:
    """Thread-safe resource reservation and usage ledger for one run."""

    def __init__(self, policy: Any) -> None:
        self._limits = {
            "model_calls": int(policy.max_model_calls),
            "tool_calls": int(policy.max_tool_calls),
            "retrievals": int(policy.max_retrievals),
        }
        self._reserved = {key: 0 for key in self._limits}
        self._usage = ResourceUsage()
        self._lock = RLock()

    def reserve(self, resource: str, amount: int = 1) -> bool:
        requested = max(0, int(amount))
        with self._lock:
            if resource not in self._limits:
                raise ValueError(f"unknown budget resource: {resource}")
            if self._reserved[resource] + requested > self._limits[resource]:
                return False
            self._reserved[resource] += requested
            return True

    def record(self, usage: ResourceUsage) -> None:
        with self._lock:
            self._usage = ResourceUsage(
                input_tokens=_optional_sum(self._usage.input_tokens, usage.input_tokens),
                output_tokens=_optional_sum(self._usage.output_tokens, usage.output_tokens),
                tool_calls=self._usage.tool_calls + usage.tool_calls,
                model_calls=self._usage.model_calls + usage.model_calls,
                elapsed_ms=_optional_sum(self._usage.elapsed_ms, usage.elapsed_ms),
            )

    @property
    def usage(self) -> ResourceUsage:
        with self._lock:
            return self._usage.model_copy(deep=True)


class AgentResourceManager:
    """Per-run budget and concurrency limits backed by shared process slots."""

    def __init__(self, policy: Any) -> None:
        self.budget = SharedRunBudget(policy)
        self._expert_slots = BoundedSemaphore(int(policy.max_parallel_experts))
        self._gpu_slots = BoundedSemaphore(1)

    @contextmanager
    def acquire(self, resource_class: str) -> Iterator[None]:
        with ExitStack() as resources:
            resources.enter_context(self._expert_slots)
            resources.enter_context(GLOBAL_EXPERT_SLOTS)
            if str(resource_class).casefold() == "gpu":
                resources.enter_context(self._gpu_slots)
                resources.enter_context(GLOBAL_GPU_SLOTS)
            yield


__all__ = [
    "GLOBAL_EXPERT_SLOTS",
    "GLOBAL_GPU_SLOTS",
    "AgentResourceManager",
    "SharedRunBudget",
]
