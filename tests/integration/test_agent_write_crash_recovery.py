from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from time import sleep

import pytest

from backend.agent_core.reliability import AgentRunControl
from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolModel,
    EmptyToolResultData,
    typed_tool_definition,
)
from backend.models.agent_run import AgentRunStatus, AgentToolCallStatus
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_tool_execution_service import AgentToolExecutionService

_PROCESS_CODE = r"""
import os
import sys
from pathlib import Path

from backend.agent_core.reliability import AgentRunControl
from backend.agent_tools.base import AgentToolModel, EmptyToolResultData, typed_tool_definition
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_tool_execution_service import AgentToolExecutionService

runtime_path, side_effect_path = sys.argv[1:]
store = AgentRunStore(storage_path=runtime_path)
run = AgentRunScheduler(store).enqueue(
    goal="Crash during write",
    task_id="task-write-crash",
    run_id="run-write-crash",
    trace_id="trace-write-crash",
    request_payload={"user_message": "write once"},
)
store.claim_run(lease_owner="write-process-a", lease_seconds=0.2)

class Args(AgentToolModel):
    value: str

def write(_context, _args):
    path = Path(side_effect_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("physical-write\\n")
        handle.flush()
        os.fsync(handle.fileno())
    os._exit(23)

definition = typed_tool_definition(
    name="write_probe",
    title="Write probe",
    description="Crash acceptance write tool",
    category="test",
    effect="write",
    requires_reading_context=False,
    requires_confirmation=True,
    args_model=Args,
    result_model=EmptyToolResultData,
    executor=write,
    retry_policy="never",
)

class Registry:
    def get_definition(self, name):
        return definition if name == "write_probe" else None

    def execute(self, name, **payload):
        result = definition.executor(None, definition.parse_args(payload))
        return definition.normalize_execution_result(result)

service = AgentToolExecutionService(Registry(), store=store)
service.execute(
    "write_probe",
    {"value": "same"},
    control=AgentRunControl(),
    run_id=run.run_id,
    step_id="step-write",
    write_confirmed=True,
)
"""


class Args(AgentToolModel):
    value: str


class Registry:
    def __init__(self, side_effect_path: Path) -> None:
        self.side_effect_path = side_effect_path
        self.definition = typed_tool_definition(
            name="write_probe",
            title="Write probe",
            description="Crash acceptance write tool",
            category="test",
            effect="write",
            requires_reading_context=False,
            requires_confirmation=True,
            args_model=Args,
            result_model=EmptyToolResultData,
            executor=self._write,
            retry_policy="never",
        )

    def _write(self, _context, _args):
        with self.side_effect_path.open("a", encoding="utf-8") as handle:
            handle.write("physical-write\n")
        return AgentToolExecutionResult(
            tool_name="write_probe",
            output_text="written",
            effect="write",
        )

    def get_definition(self, name):
        return self.definition if name == "write_probe" else None

    def execute(self, name, **payload):
        result = self.definition.executor(None, self.definition.parse_args(payload))
        return self.definition.normalize_execution_result(result)


def _physical_write_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line])


def test_write_side_effect_is_not_replayed_after_real_process_crash(tmp_path) -> None:
    repository = Path(__file__).resolve().parents[2]
    runtime_path = tmp_path / "runtime.sqlite3"
    side_effect_path = tmp_path / "physical-writes.log"

    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROCESS_CODE,
            str(runtime_path),
            str(side_effect_path),
        ],
        capture_output=True,
        text=True,
        cwd=repository,
        timeout=30,
        check=False,
    )
    assert crashed.returncode == 23, crashed.stderr
    assert _physical_write_count(side_effect_path) == 1

    with sqlite3.connect(runtime_path) as connection:
        row = connection.execute(
            "SELECT tool_call_id, status FROM agent_tool_calls WHERE run_id = ?",
            ("run-write-crash",),
        ).fetchone()
    assert row is not None
    tool_call_id = str(row[0])
    assert str(row[1]) == "running"

    sleep(0.3)
    store = AgentRunStore(storage_path=runtime_path)
    assert store.recover_expired_runs() == ("run-write-crash",)
    assert store.get_run("run-write-crash").status is AgentRunStatus.RECOVERING

    claimed = store.claim_run(lease_owner="write-process-b", lease_seconds=30)
    assert claimed is not None and claimed.run_id == "run-write-crash"
    blocked = store.prepare_recovery_tool_calls(
        "run-write-crash",
        lease_owner="write-process-b",
    )
    assert blocked == (tool_call_id,)
    assert store.get_tool_call(tool_call_id).status is AgentToolCallStatus.BLOCKED_RECOVERY

    replacement = AgentToolExecutionService(
        Registry(side_effect_path),
        store=store,
    )
    with pytest.raises(Exception, match="existing unresolved call"):
        replacement.execute(
            "write_probe",
            {"value": "same"},
            control=AgentRunControl(),
            run_id="run-write-crash",
            step_id="step-write",
            write_confirmed=True,
        )

    assert _physical_write_count(side_effect_path) == 1
    waiting = store.finish_owned_run(
        "run-write-crash",
        lease_owner="write-process-b",
        target_status=AgentRunStatus.WAITING,
        result_payload={
            "code": "write_recovery_blocked",
            "tool_call_ids": [tool_call_id],
        },
    )
    assert waiting.status is AgentRunStatus.WAITING
    assert store.get_run_result("run-write-crash")["code"] == "write_recovery_blocked"
