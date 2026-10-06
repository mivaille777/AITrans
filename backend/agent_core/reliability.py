from __future__ import annotations

from collections.abc import Callable
from contextvars import copy_context
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, RLock, Thread
from time import monotonic
from typing import TypeVar

from app.ai.errors import (
    AIConnectionError,
    AIResponseError,
    AITimeoutError,
)
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentDecisionTimeoutError,
    AgentPauseRequestedError,
    AgentToolTimeoutError,
)
from backend.rag.inference_worker import inference_cancellation

T = TypeVar("T")


def is_transient_provider_error(error: Exception) -> bool:
    """Return true only for known transient provider/network failures.

    Authentication, configuration, rate-limit, malformed-response, runtime,
    permission, scope, budget and cancellation errors are deliberately excluded.
    """

    if isinstance(error, (AIConnectionError, AITimeoutError, OSError, TimeoutError)):
        return True
    if isinstance(error, AgentDecisionTimeoutError):
        return True
    return isinstance(error, AIResponseError) and (error.status_code or 0) >= 500


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
    node_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 20.0
    max_safe_retries: int = 1
    max_plan_steps: int = 4
    max_tool_calls: int = 4
    max_react_iterations: int = 6
    max_knowledge_searches: int = 3
    max_knowledge_reads: int = 6
    react_decision_timeout_seconds: float = 12.0
    max_observation_chars: int = 3000

    def __post_init__(self) -> None:
        if self.total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if self.node_timeout_seconds <= 0:
            raise ValueError("node_timeout_seconds must be positive")
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
        if self.max_knowledge_reads < 1:
            raise ValueError("max_knowledge_reads must be positive")
        if self.react_decision_timeout_seconds <= 0:
            raise ValueError("react_decision_timeout_seconds must be positive")
        if self.max_observation_chars < 1:
            raise ValueError("max_observation_chars must be positive")


@dataclass(slots=True)
class AgentRunControl:
    policy: AgentExecutionPolicy = field(default_factory=AgentExecutionPolicy)
    cancel_event: Event = field(default_factory=Event)
    pause_event: Event = field(default_factory=Event)
    started_at: float = field(default_factory=monotonic)
    knowledge_search_count: int = 0
    knowledge_read_count: int = 0
    skill_session: object | None = field(default=None, repr=False)
    _fence_lock: RLock = field(default_factory=RLock, repr=False)

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
        with self._fence_lock:
            self.cancel_event.set()

    def commit_if_active(self, stage: str, operation: Callable[[], T]) -> T:
        """Fence a short irreversible commit against a concurrent cancellation."""

        with self._fence_lock:
            self.checkpoint(stage)
            return operation()

    def pause(self) -> None:
        self.pause_event.set()

    def pause_at_boundary(self, node: str) -> None:
        self.checkpoint(node)
        if self.pause_event.is_set():
            raise AgentPauseRequestedError(f"Agent run paused before {node}.")

    def checkpoint(self, stage: str) -> None:
        if self.cancel_event.is_set():
            raise AgentCancelledError(f"Agent run cancelled before {stage}.")
        if self.remaining_seconds <= 0:
            raise AgentBudgetExceededError(
                f"Agent execution budget exceeded before {stage}."
            )

    def bounded_tool_timeout(self) -> float:
        return min(self.policy.tool_timeout_seconds, self.remaining_seconds)

    def bounded_node_timeout(self, node_timeout_seconds: float) -> float:
        """Bound a node operation by both its local deadline and the run budget."""

        return min(max(0.0, float(node_timeout_seconds)), self.remaining_seconds)

    def bounded_react_decision_timeout(self) -> float:
        timeout = self.policy.react_decision_timeout_seconds
        if self.skill_session is not None and self.skill_session.function_names:
            # One decision can include bounded metadata/activation/resource calls.
            timeout = max(timeout, 60.0)
        return min(
            timeout,
            self.remaining_seconds,
        )

    def claim_knowledge_action(self, tool_name: str) -> None:
        """Enforce separate per-run Locate and Read budgets."""

        normalized = str(tool_name or "").strip()
        if normalized == "search_knowledge_base":
            limit = min(
                self.policy.max_knowledge_searches,
                self.policy.max_tool_calls,
            )
            if self.knowledge_search_count >= limit:
                raise AgentBudgetExceededError(
                    "Agent knowledge search budget is exhausted."
                )
            self.knowledge_search_count += 1
        elif normalized in {"read_knowledge_chunk", "read_knowledge_section"}:
            limit = min(
                self.policy.max_knowledge_reads,
                self.policy.max_tool_calls,
            )
            if self.knowledge_read_count >= limit:
                raise AgentBudgetExceededError(
                    "Agent knowledge read budget is exhausted."
                )
            self.knowledge_read_count += 1


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
    stop_event = Event()

    def worker() -> None:
        try:
            with inference_cancellation(lambda: stop_event.is_set() or control.cancel_event.is_set() or control.pause_event.is_set()):
                queue.put((True, operation()))
        except BaseException as exc:  # noqa: BLE001 - preserve interruptions across the worker boundary
            queue.put((False, exc))

    thread = Thread(target=copy_context().run, args=(worker,), name=thread_name, daemon=True)
    thread.start()
    started = monotonic()
    try:
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
            if isinstance(value, BaseException):
                raise value
            raise RuntimeError(f"Agent operation {stage} failed without an exception.")
    finally:
        stop_event.set()
        thread.join(timeout=0.5)


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


def run_node_operation_with_timeout(
    operation: Callable[[], T],
    *,
    control: AgentRunControl,
    node_timeout_seconds: float,
    stage: str,
) -> T:
    """Run a side-effect-free Root decision within its node and run deadlines."""

    timeout = control.bounded_node_timeout(node_timeout_seconds)
    return _run_bounded_operation(
        operation,
        control=control,
        timeout=timeout,
        stage=stage,
        thread_name=f"agent-node-{stage}",
        timeout_error=lambda value: AgentDecisionTimeoutError(
            f"Agent node {stage} exceeded {value:.2f}s timeout."
        ),
    )


def run_safe_tool_with_timeout(
    operation: Callable[[], T],
    *,
    control: AgentRunControl,
    tool_name: str,
    timeout_seconds: float | None = None,
) -> T:
    """Run a read/compute tool with cooperative cancellation and a hard wait bound.

    The worker is daemonized because Python cannot safely interrupt a blocking
    provider call. This helper must therefore never wrap write tools or other
    side-effectful operations.
    """

    timeout = control.bounded_tool_timeout()
    if timeout_seconds is not None:
        timeout = min(timeout, timeout_seconds)
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
    "is_transient_provider_error",
    "run_node_operation_with_timeout",
    "run_react_decision_with_timeout",
    "run_safe_tool_with_timeout",
]
