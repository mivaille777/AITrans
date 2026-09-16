from __future__ import annotations

from backend.agent_core.orchestration.parallel_executor import SQLiteTaskCheckpointStore


def test_only_one_owner_can_hold_a_live_run_lease(tmp_path) -> None:
    now = [100.0]
    store = SQLiteTaskCheckpointStore(
        tmp_path / "leases.sqlite3",
        clock=lambda: now[0],
    )

    assert store.acquire_lease(
        run_id="run-1", plan_hash="plan-1", owner_id="window-a", lease_seconds=10
    )
    assert not store.acquire_lease(
        run_id="run-1", plan_hash="plan-1", owner_id="window-b", lease_seconds=10
    )

    now[0] = 111.0
    assert store.acquire_lease(
        run_id="run-1", plan_hash="plan-1", owner_id="window-b", lease_seconds=10
    )


def test_released_lease_is_immediately_available(tmp_path) -> None:
    store = SQLiteTaskCheckpointStore(tmp_path / "leases.sqlite3")
    assert store.acquire_lease(
        run_id="run-2", plan_hash="plan-2", owner_id="window-a", lease_seconds=30
    )
    store.release_lease("run-2", "window-a")
    assert store.acquire_lease(
        run_id="run-2", plan_hash="plan-2", owner_id="window-b", lease_seconds=30
    )
