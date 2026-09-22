from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

from backend.models.agent_run import AgentRunStatus
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore

_PROCESS_CODE = r"""
import asyncio
import sys
from pathlib import Path

from backend.models.agent_run import AgentRunStatus
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_run_worker import AgentRunWorker

runtime_path, start_flag, execution_log, worker_id = sys.argv[1:]
store = AgentRunStore(storage_path=runtime_path)

async def execute(run, _control, _recovering):
    path = Path(execution_log)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(worker_id + "\\n")
        handle.flush()
    await asyncio.sleep(0.15)
    return AgentRunStatus.COMPLETED

async def main():
    flag = Path(start_flag)
    for _ in range(500):
        if flag.exists():
            break
        await asyncio.sleep(0.01)
    else:
        raise RuntimeError("start barrier was not released")

    worker = AgentRunWorker(
        store,
        execute,
        worker_id=worker_id,
        lease_seconds=2.0,
        heartbeat_seconds=0.25,
        poll_seconds=0.02,
    )
    result = await worker.run_once()
    print(result.status.value if result is not None else "idle", flush=True)

asyncio.run(main())
"""


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_multiple_process_workers_execute_one_run_exactly_once(tmp_path) -> None:
    repository = Path(__file__).resolve().parents[2]
    runtime_path = tmp_path / "runtime.sqlite3"
    start_flag = tmp_path / "start.flag"
    execution_log = tmp_path / "executions.log"

    store = AgentRunStore(storage_path=runtime_path)
    run = AgentRunScheduler(store).enqueue(
        goal="Compete for exactly one durable run",
        task_id="task-concurrency",
        run_id="run-concurrency",
        trace_id="trace-concurrency",
        request_payload={"user_message": "concurrency acceptance"},
    )
    store.close()

    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _PROCESS_CODE,
                str(runtime_path),
                str(start_flag),
                str(execution_log),
                f"process-worker-{index}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=repository,
        )
        for index in range(8)
    ]

    sleep(0.15)
    start_flag.write_text("go", encoding="utf-8")

    outputs: list[str] = []
    deadline = monotonic() + 30
    for process in workers:
        remaining = max(1.0, deadline - monotonic())
        stdout, stderr = process.communicate(timeout=remaining)
        assert process.returncode == 0, stderr
        outputs.append(stdout.strip())

    executions = _lines(execution_log)
    assert len(executions) == 1
    assert executions[0].startswith("process-worker-")
    assert outputs.count("completed") == 1
    assert outputs.count("idle") == 7

    reopened = AgentRunStore(storage_path=runtime_path)
    final = reopened.get_run(run.run_id)
    assert final is not None
    assert final.status is AgentRunStatus.COMPLETED
    assert final.task_id == "task-concurrency"
    assert final.trace_id == "trace-concurrency"
    assert reopened.get_lease(run.run_id) is None
