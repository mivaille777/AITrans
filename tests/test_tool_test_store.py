import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.tool_test import ToolTestRun
from backend.services.tool_management_service import ToolManagementError
from backend.services.tool_test_store import ToolTestStore


def record(n, **values):
    stamp = (datetime.now(UTC) + timedelta(microseconds=n)).isoformat()
    return ToolTestRun(
        **{
            "test_run_id": f"test_{n}",
            "tool_id": "builtin:test",
            "tool_name": "test",
            "tool_call_id": f"call_{n}",
            "trace_id": f"trace_{n}",
            "created_at": stamp,
            "updated_at": stamp,
            **values,
        }
    )


def test_recovery_invalidates_pending_grants_and_keeps_uncertain_workers(tmp_path):
    store = ToolTestStore(tmp_path / "agent_runtime.sqlite3")
    for run in [
        record(
            1,
            status="awaiting_approval",
            approval_id="approval",
            approval_summary={"source_text": "sensitive"},
        ),
        record(2, status="running", execution_state="running"),
    ]:
        store.claim(run, run.test_run_id, "hash")
    store.recover()
    pending = store.get("builtin:test", "test_1")
    assert pending.status == "interrupted" and pending.approval_id is None
    assert pending.execution_state == "stopped"
    worker = store.get("builtin:test", "test_2")
    assert worker.status == "interrupted" and worker.execution_state == "unknown"
    assert "sensitive" not in store.path.read_bytes().decode(errors="ignore")
    assert (
        store.find("builtin:test", "test_2", "hash").test_run_id == worker.test_run_id
    )
    with pytest.raises(ToolManagementError, match="different input"):
        store.find("builtin:test", "test_2", "other")


def test_retention_protects_active_and_unknown_and_prunes_events(tmp_path):
    store = ToolTestStore(tmp_path / "runtime.sqlite3")
    for n in range(110):
        run = record(
            n,
            status="succeeded",
            execution_state="stopped",
            finished_at=datetime.now(UTC).isoformat(),
        )
        store.claim(run, str(n), "hash")
    store.claim(record(111, status="awaiting_approval"), "pending", "hash")
    store.claim(
        record(
            112,
            status="interrupted",
            execution_state="unknown",
            finished_at=datetime.now(UTC).isoformat(),
        ),
        "unknown",
        "hash",
    )
    assert len(store.prune()) == 10
    assert store.get("builtin:test", "test_0") is None
    assert store.events("test_0") == []
    assert store.get("builtin:test", "test_111") is not None
    assert store.get("builtin:test", "test_112") is not None
    assert len(store.history("builtin:test", limit=100)["items"]) == 100


def test_same_timestamp_history_cursor_and_event_replay_are_stable(tmp_path):
    store = ToolTestStore(tmp_path / "runtime.sqlite3")
    stamp = datetime.now(UTC).isoformat()
    for n in range(3):
        run = record(n, created_at=stamp)
        store.claim(run, str(n), "hash")
        store.save(
            run.model_copy(
                update={
                    "status": "succeeded",
                    "execution_state": "stopped",
                    "finished_at": stamp,
                    "error": {"code": "sample", "message": "secret"},
                }
            )
        )
    page = store.history("builtin:test", limit=2)
    second = store.history("builtin:test", limit=2, before=page["next_cursor"])
    assert len({x["test_run_id"] for x in page["items"] + second["items"]}) == 3
    events = store.events("test_0")
    assert [x["seq"] for x in events] == [1, 2]
    assert store.events("test_0", 1) == events[1:]
    assert "secret" not in json.dumps(events)
    with pytest.raises(ToolManagementError):
        store.history("builtin:other", before=page["next_cursor"])
