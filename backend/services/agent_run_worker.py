from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from uuid import uuid4

from backend.agent_core.exceptions import AgentPauseRequestedError
from backend.agent_core.reliability import AgentRunControl
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.services.agent_run_scheduler import PROFILE_BUDGETS
from backend.services.agent_run_store import AgentRunStore, AgentRunStoreConflictError


@dataclass(frozen=True, slots=True)
class AgentRunOutcome:
    status: AgentRunStatus
    result: dict[str, object]


AgentRunExecutor = Callable[
    [AgentRunRecord, AgentRunControl, bool],
    Awaitable[AgentRunStatus | AgentRunOutcome | None],
]
_logger = logging.getLogger(__name__)


class AgentRunWorker:
    """Local asyncio worker; SQLite leases fence stale completions."""

    def __init__(
        self,
        store: AgentRunStore,
        executor: AgentRunExecutor,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 15.0,
        heartbeat_seconds: float = 3.0,
        poll_seconds: float = 0.5,
    ) -> None:
        if lease_seconds <= 0 or heartbeat_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("worker intervals must be positive")
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat interval must be shorter than lease")
        self.store = store
        self.executor = executor
        self.worker_id = worker_id or f"worker-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds

    async def _heartbeat(
        self,
        run_id: str,
        control: AgentRunControl,
        execution: asyncio.Task[AgentRunStatus | AgentRunOutcome | None],
        base_budget_ms: int,
    ) -> None:
        while not execution.done():
            await asyncio.sleep(self.heartbeat_seconds)
            if execution.done():
                return
            try:
                alive = await asyncio.to_thread(
                    self.store.heartbeat_lease,
                    run_id,
                    lease_owner=self.worker_id,
                    lease_seconds=self.lease_seconds,
                    budget_used_ms=base_budget_ms + control.elapsed_ms,
                )
            except Exception:
                _logger.exception("Unable to renew lease for run %s", run_id)
                alive = False
            if not alive:
                control.cancel()
                execution.cancel()
                return
            current = await asyncio.to_thread(self.store.get_run, run_id)
            if current is not None and current.status is AgentRunStatus.PAUSE_REQUESTED:
                control.pause()

    async def run_once(self) -> AgentRunRecord | None:
        await asyncio.to_thread(self.store.recover_expired_runs)
        claim = await asyncio.to_thread(
            self.store.claim_next_run,
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return None
        run, recovering = claim
        budget = PROFILE_BUDGETS[run.runtime_profile]
        remaining = budget.policy.total_timeout_seconds - run.budget_used_ms / 1000
        if remaining <= 0:
            return await asyncio.to_thread(
                self.store.finish_owned_run,
                run.run_id,
                lease_owner=self.worker_id,
                target_status=AgentRunStatus.FAILED,
                result_payload={"code": "execution_budget_exhausted"},
            )
        control = AgentRunControl(
            policy=replace(budget.policy, total_timeout_seconds=remaining)
        )
        execution = asyncio.create_task(self.executor(run, control, recovering))
        heartbeat = asyncio.create_task(
            self._heartbeat(run.run_id, control, execution, run.budget_used_ms)
        )
        target = AgentRunStatus.COMPLETED
        result_payload = None
        try:
            outcome = await asyncio.wait_for(execution, timeout=remaining)
            if isinstance(outcome, AgentRunOutcome):
                target = outcome.status
                result_payload = outcome.result
            elif outcome is not None:
                target = outcome
        except asyncio.CancelledError:
            control.cancel()
            if not execution.done():
                execution.cancel()
            if asyncio.current_task().cancelling():
                raise
            target = AgentRunStatus.FAILED
        except AgentPauseRequestedError:
            target = AgentRunStatus.PAUSED
        except Exception:
            _logger.exception("Agent run %s failed", run.run_id)
            target = AgentRunStatus.FAILED
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        try:
            return await asyncio.to_thread(
                self.store.finish_owned_run,
                run.run_id,
                lease_owner=self.worker_id,
                target_status=target,
                result_payload=result_payload,
                budget_used_ms=run.budget_used_ms + control.elapsed_ms,
            )
        except AgentRunStoreConflictError:
            # Cancellation or lease takeover is authoritative; the old worker
            # must never overwrite the status chosen by the current owner.
            return await asyncio.to_thread(self.store.get_run, run.run_id)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("Agent run worker failed; retrying")
                processed = None
            if processed is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass


__all__ = ["AgentRunExecutor", "AgentRunOutcome", "AgentRunWorker"]
