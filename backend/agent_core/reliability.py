from __future__ import annotations

from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Callable, TypeVar

from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentDecisionTimeoutError,
    AgentToolTimeoutError,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AgentExecutionPolicy:
    """Bounded execution policy for one Agent run.

    Retries are intentionally limited to read/compute tools by ProductAgentService.
    Write tools are never automatically retried. Multi-step and ReAct
    orchestration are both hard-bounded so LangGraph loops cannot grow without
    limit. Agentic knowledge retrieval also has its own budget so iterative RAG
    cannot consume every available Tool call.
    """

    total_timeout_seconds: float = 45.0
    tool_timeout_seconds: float = 20.0
    max_safe_retries: int = 1
    max_plan_steps: int = 4
    max_tool_calls: int = 4
    max_react_iterations: int = 6
    max_knowledge_searches: int = 3
    react_decision_timeout_seconds: float = 12.0
    max_observation_chars: int = 3000

    def __post_init__(self) -> None:
        if self.total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")
        if self.max_safe_retries < 0:
            raise ValueError("max_safe_retries must be non-negative")
        if self.max_plan_steps < 2:
            raise ValueError("max_plan_steps must be at least 2")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        if self.max_react_iterations < 1:
            raise ValueError("max_react_iterations must be positive")
        if self.max_knowledge_searches < 1:
            raise ValueError("max_knowledge_searches must be positive")
        if self.react_decision_timeout_seconds <= 0:
            raise ValueError("react_decision_timeout_seconds must be positive")
        if self.max_observation_chars < 1:
            raise ValueError("max_observation_chars must be positive")


@dataclass(slots=True)
class AgentRunControl:
    policy: AgentExecutionPolicy = field(default_factory=AgentExecutionPolicy)
    cancel_event: Event = field(default_factory=Event)
    started_at: float = field(default_factory=monotonic)

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self.started_at)

    @property
    def elapsed_ms(self) -> int:
        return int(self.elapsed_seconds * 1000)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.policy.total_timeout_seconds - self.elapsed_seconds)

    def cancel(self) -> None:
        self.cancel_event.set()

    def checkpoint(self, stage: str) -> None:
        if self.cancel_event.is_set():
            raise AgentCancelledError(f"Agent run cancelled before {stage}.")
        if self.remaining_seconds <= 0:
            raise AgentBudgetExceededError(
                f"Agent execution budget exceeded before {stage}."
            )

    def bounded_tool_timeout(self) -> float:
        return min(self.policy.tool_timeout_seconds, self.remaining_seconds)

    def bounded_react_decision_timeout(self) -> float:
        return min(
            self.policy.react_decision_timeout_seconds,
            self.remaining_seconds,
        )


def _run_bounded_operation(
    operation: Callable[[], T],
    *,
    control: AgentRunControl,
    timeout: float,
    stage: str,
    thread_name: str,
    timeout_error: Callable[[float], Exception],
) -> T:
    control.checkpoint(stage)
    if timeout <= 0:
        raise AgentBudgetExceededError(
            f"Agent execution budget exhausted before {stage}."
        )

    queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def worker() -> None:
        try:
            queue.put((True, operation()))
        except Exception as exc:
            queue.put((False, exc))

    Thread(target=worker, name=thread_name, daemon=True).start()
    started = monotonic()
    while True:
        control.checkpoint(stage)
        elapsed = monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            raise timeout_error(timeout)
        try:
            ok, value = queue.get(timeout=min(0.05, remaining))
        except Empty:
            continue
        if ok:
            return value  # type: ignore[return-value]
        if isinstance(value, Exception):
            raise value
        raise RuntimeError(f"Agent operation {stage} failed without an exception.")


def run_react_decision_with_timeout(
    operation: Callable[[], T],
    *,
    control: AgentRunControl,
) -> T:
    """Run one side-effect-free ReAct decision under the decision time budget."""

    timeout = control.bounded_react_decision_timeout()
    return _run_bounded_operation(
        operation,
        control=control,
        timeout=timeout,
        stage="react_decision",
        thread_name="agent-react-decision",
        timeout_error=lambda value: AgentDecisionTimeoutError(
            f"Agent ReAct decision exceeded {value:.2f}s timeout."
        ),
    )


def run_safe_tool_with_timeout(
    operation: Callable[[], T],
    *,
    control: AgentRunControl,
    tool_name: str,
) -> T:
    """Run a read/compute tool with cooperative cancellation and a hard wait bound.

    The worker is daemonized because Python cannot safely interrupt a blocking
    provider call. This helper must therefore never wrap write tools or other
    side-effectful operations.
    """

    timeout = control.bounded_tool_timeout()
    return _run_bounded_operation(
        operation,
        control=control,
        timeout=timeout,
        stage=f"tool:{tool_name}",
        thread_name=f"agent-tool-{tool_name}",
        timeout_error=lambda value: AgentToolTimeoutError(
            f"Agent tool {tool_name} exceeded {value:.2f}s timeout."
        ),
    )


__all__ = [
    "AgentExecutionPolicy",
    "AgentRunControl",
    "run_react_decision_with_timeout",
    "run_safe_tool_with_timeout",
]
