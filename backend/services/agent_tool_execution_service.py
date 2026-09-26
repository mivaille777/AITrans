"""Durable, effect-aware boundary for product agent tool execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from app.ai.errors import AIConfigurationError, AIError
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentRuntimeError,
    AgentToolError,
    AgentToolTimeoutError,
)
from backend.agent_core.reliability import AgentRunControl, run_safe_tool_with_timeout
from backend.agent_tools.base import AgentToolExecutionResult
from backend.models.agent_run import AgentToolCallRecord, AgentToolCallStatus
from backend.services.agent_run_store import AgentRunStore

_BOUND_STORE: ContextVar[AgentRunStore | None] = ContextVar("agent_tool_run_store", default=None)


@contextmanager
def bind_tool_run_store(store: AgentRunStore) -> Iterator[None]:
    token = _BOUND_STORE.set(store)
    try:
        yield
    finally:
        _BOUND_STORE.reset(token)


def bound_tool_run_store() -> AgentRunStore | None:
    return _BOUND_STORE.get()


def _retryable(error: Exception) -> bool:
    if isinstance(error, (AIConfigurationError, AgentCancelledError,
                          AgentBudgetExceededError, AgentToolTimeoutError,
                          ValueError, PermissionError)):
        return False
    return isinstance(error, (AIError, OSError, TimeoutError, AgentRuntimeError))


def _digest(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    step_id: str
    tool_name: str
    payload: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    exclusive_resource: str = ""
    write_confirmed: bool = False


class AgentToolExecutionService:
    """Persist a ToolCall before invoking a Tool; never replay uncertain writes."""

    def __init__(
        self, registry: Any, *, store: AgentRunStore | None = None,
        retry_sleep: Callable[[float], None] = sleep,
    ) -> None:
        self.registry = registry
        self.store = store
        self.retry_sleep = retry_sleep

    def execute_many(
        self, requests: list[ToolExecutionRequest], *, control: AgentRunControl,
        run_id: str = "", max_parallel: int = 4,
    ) -> dict[str, AgentToolExecutionResult]:
        """Run independent reads concurrently; writes and shared resources serialize."""
        if not 1 <= max_parallel <= 4:
            raise ValueError("max_parallel must be between 1 and 4")
        pending = {item.step_id: item for item in requests}
        if len(pending) != len(requests):
            raise ValueError("duplicate step_id")
        if any(set(item.depends_on) - set(pending) for item in requests):
            raise ValueError("unknown tool dependency")
        worker_service = AgentToolExecutionService(
            self.registry, store=self.store or bound_tool_run_store(),
            retry_sleep=self.retry_sleep,
        )
        outputs: dict[str, AgentToolExecutionResult] = {}
        while pending:
            ready = [item for item in pending.values()
                     if set(item.depends_on) <= set(outputs)]
            if not ready:
                raise ValueError("cyclic tool dependencies")
            batch: list[ToolExecutionRequest] = []
            resources: set[str] = set()
            for item in ready:
                definition = self.registry.get_definition(item.tool_name)
                if definition is None:
                    raise KeyError(item.tool_name)
                spec = definition.spec
                if spec.effect == "write" or not spec.parallel_safe:
                    if not batch:
                        batch = [item]
                    break
                if item.exclusive_resource and item.exclusive_resource in resources:
                    continue
                batch.append(item)
                if item.exclusive_resource:
                    resources.add(item.exclusive_resource)
                if len(batch) >= max_parallel:
                    break
            if len(batch) == 1:
                item = batch[0]
                outputs[item.step_id] = worker_service.execute(
                    item.tool_name, item.payload, control=control,
                    run_id=run_id, step_id=item.step_id,
                    write_confirmed=item.write_confirmed,
                )
            else:
                with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    futures = {
                        item.step_id: executor.submit(
                            worker_service.execute, item.tool_name, item.payload,
                            control=control, run_id=run_id, step_id=item.step_id,
                            write_confirmed=item.write_confirmed,
                        ) for item in batch
                    }
                    for step_id, future in futures.items():
                        outputs[step_id] = future.result()
            for item in batch:
                del pending[item.step_id]
        return outputs

    def execute(
        self, name: str, payload: dict[str, Any], *, control: AgentRunControl,
        run_id: str = "", step_id: str = "direct",
        emit_retry: Callable[[int, int, Exception, str], None] | None = None,
        on_call: Callable[[str], None] | None = None,
        write_confirmed: bool = False,
    ) -> AgentToolExecutionResult:
        definition = self.registry.get_definition(name)
        if definition is None:
            raise KeyError(f"Unknown agent tool: {name}")
        spec = definition.spec
        if spec.effect not in {"read", "compute", "write"}:
            raise ValueError(f"Agent tool {name} has no valid effect")
        if spec.effect == "write" and (definition.allows_safe_retry or spec.parallel_safe):
            raise ValueError(f"Agent write tool {name} has unsafe execution metadata")
        if spec.effect == "write" and spec.requires_confirmation and not write_confirmed:
            raise AgentToolError(
                f"Agent write tool {name} requires confirmation.",
                stage="tool", fallback_reason="write_confirmation_required",
            )
        # Validate before recording a call. A rejected input has no side effect.
        arguments = definition.parse_args(payload).model_dump(mode="json")
        arguments_hash = _digest(arguments)
        effective_run_id = run_id or str(payload.get("run_id", ""))
        effective_step_id = step_id or "direct"
        idempotency_key = _digest((effective_run_id, effective_step_id, name,
                                   arguments_hash, spec.tool_version))
        call = AgentToolCallRecord(
            tool_call_id=uuid4().hex, run_id=effective_run_id or "untracked",
            step_id=effective_step_id, tool_name=name, effect=spec.effect,
            arguments_hash=arguments_hash, idempotency_key=idempotency_key,
            timeout_ms=max(1, int(spec.timeout_seconds * 1000)),
        )
        store = self.store or bound_tool_run_store()
        if store is not None and effective_run_id:
            call, owned, saved = store.claim_tool_call(call)
            if not owned:
                if call.status is AgentToolCallStatus.SUCCEEDED and saved is not None:
                    if on_call:
                        on_call(call.tool_call_id)
                    return AgentToolExecutionResult(**saved)
                # A concurrent caller may be waiting for the owner. A stale or
                # crashed write is deliberately blocked, never physically replayed.
                until = monotonic() + min(5.0, control.remaining_seconds)
                while call.status in {AgentToolCallStatus.PENDING, AgentToolCallStatus.RUNNING} and monotonic() < until:
                    sleep(0.01)
                    call = store.get_tool_call(call.tool_call_id) or call
                    if call.status is AgentToolCallStatus.SUCCEEDED:
                        saved = store.get_tool_call_result(call.tool_call_id)
                        if saved is not None:
                            if on_call:
                                on_call(call.tool_call_id)
                            return AgentToolExecutionResult(**saved)
                raise AgentToolError(
                    f"Agent tool {name} has an existing unresolved call {call.tool_call_id}.",
                    stage="tool", fallback_reason="tool_call_already_claimed",
                )
        if on_call:
            on_call(call.tool_call_id)
        call.status = AgentToolCallStatus.RUNNING
        call.started_at = datetime.now(UTC)
        if store is not None and effective_run_id:
            store.finish_tool_call(call)
        max_attempts = 1
        if spec.effect != "write" and definition.allows_safe_retry:
            max_attempts = min(3, 1 + control.policy.max_safe_retries)
        try:
            for attempt in range(1, max_attempts + 1):
                call.attempt = attempt
                control.checkpoint(f"tool:{name}:attempt:{attempt}")
                try:
                    if spec.effect == "write":
                        result = self.registry.execute(
                            name,
                            **{**payload, "tool_call_id": call.tool_call_id},
                        )
                    else:
                        result = run_safe_tool_with_timeout(
                            lambda: self.registry.execute(
                                name,
                                **{**payload, "tool_call_id": call.tool_call_id},
                            ),
                            control=control, tool_name=name,
                            timeout_seconds=spec.timeout_seconds,
                        )
                    call.status = AgentToolCallStatus.SUCCEEDED
                    call.finished_at = datetime.now(UTC)
                    if store is not None and effective_run_id:
                        store.finish_tool_call(call, result=asdict(result))
                    return result
                except Exception as error:
                    if not _retryable(error) or attempt == max_attempts:
                        if isinstance(error, AgentRuntimeError):
                            raise
                        if spec.effect == "write":
                            raise
                        raise AgentToolError(
                            f"Agent tool {name} failed after {attempt} attempt(s): {error}",
                            stage="tool", fallback_reason=(
                                "safe_tool_retries_exhausted" if _retryable(error)
                                else "tool_failure_not_retryable"),
                        ) from error
                    if emit_retry:
                        emit_retry(attempt + 1, max_attempts, error, call.tool_call_id)
                    control.checkpoint(f"tool:{name}:retry_wait")
                    self.retry_sleep(min(0.5 * (2 ** (attempt - 1)),
                                         control.remaining_seconds))
        except Exception as error:
            call.finished_at = datetime.now(UTC)
            call.error_type = type(error).__name__
            call.error_message = str(error)[:4000]
            call.status = (
                AgentToolCallStatus.TIMED_OUT if isinstance(error, AgentToolTimeoutError)
                else AgentToolCallStatus.CANCELLED if isinstance(error, AgentCancelledError)
                else AgentToolCallStatus.FAILED
            )
            if store is not None and effective_run_id:
                store.finish_tool_call(call)
            raise
        raise AssertionError("tool execution exhausted without outcome")


__all__ = ["AgentToolExecutionService", "ToolExecutionRequest", "bind_tool_run_store", "bound_tool_run_store"]
