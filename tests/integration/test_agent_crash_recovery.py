from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from time import sleep

_PROCESS_CODE = r"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.models.agent_run import AgentRunStatus
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentPlan
from backend.services.agent_checkpoint_service import AgentCheckpointService
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_run_worker import AgentRunWorker

mode, runtime_path, checkpoint_path = sys.argv[1:]
store = AgentRunStore(storage_path=runtime_path)
checkpoint = AgentCheckpointService(storage_path=checkpoint_path)

class Service:
    def resolve_route(self, **_payload):
        if mode == "crash":
            os._exit(17)
        return AgentRouteDecision(
            kind="answer", source="deterministic", intent="answer"
        ), {"llm_called": False}

    def run(self, **payload):
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(action="answer", user_visible_reason="done"),
            output_text="recovered",
            provider="test",
            model="test",
            request_id=0,
            tool_result=None,
            route=AgentRouteDecision.model_validate(payload["_resolved_route"]),
        )

runtime = AgentRuntime(
    workflow_adapter=ReadingAgentGraph(
        ProductAgentRuntimeAdapter(Service()), checkpointer=checkpoint.checkpointer
    )
)
if mode == "crash":
    run = AgentRunScheduler(store).enqueue(
        goal="Recover across processes",
        task_id="task-process-recovery",
        run_id="run-process-recovery",
        trace_id="trace-process-recovery",
        request_payload={"user_message": "Recover across processes"},
    )
    store.claim_run(lease_owner="process-a", lease_seconds=0.2)
    state = AgentState(task_id=run.task_id, run_id=run.run_id, trace_id=run.trace_id)
    runtime.execute(state, event_sink=store.append_event)
else:
    recovered_ids = store.recover_expired_runs()
    recovering_record = store.get_run("run-process-recovery")
    assert recovering_record is not None
    assert recovering_record.status is AgentRunStatus.RECOVERING

    async def execute(run, control, recovering):
        assert recovering
        state = runtime.restore_checkpoint(run.run_id)
        result = runtime.execute(
            state, control=control, resume=True, event_sink=store.append_event
        )
        assert result.run_id == run.run_id
        assert result.trace_id == run.trace_id
        return AgentRunStatus.COMPLETED

    worker = AgentRunWorker(store, execute, worker_id="process-b")
    completed = asyncio.run(worker.run_once())
    print(json.dumps({
        "task_id": completed.task_id,
        "run_id": completed.run_id,
        "trace_id": completed.trace_id,
        "pre_resume_status": recovering_record.status.value,
        "recovered_ids": list(recovered_ids),
        "status": completed.status.value,
        "context_events": sum(
            event.event_type.value == "context_ready"
            for event in store.list_events(completed.run_id)
        ),
    }), flush=True)
    checkpoint.close()
"""


def test_crashed_process_reclaims_without_repeating_checkpointed_node(tmp_path) -> None:
    repository = Path(__file__).resolve().parents[2]
    runtime_path = str(tmp_path / "runtime.sqlite3")
    checkpoint_path = str(tmp_path / "checkpoints.sqlite3")
    crash = subprocess.run(
        [sys.executable, "-c", _PROCESS_CODE, "crash", runtime_path, checkpoint_path],
        capture_output=True,
        text=True,
        cwd=repository,
        timeout=30,
        check=False,
    )
    assert crash.returncode == 17, crash.stderr

    from backend.models.agent_run import AgentRunStatus
    from backend.services.agent_run_store import AgentRunStore

    interrupted_store = AgentRunStore(storage_path=runtime_path)
    interrupted = interrupted_store.get_run("run-process-recovery")
    lease = interrupted_store.get_lease("run-process-recovery")
    assert interrupted is not None
    assert interrupted.status is AgentRunStatus.RUNNING
    assert interrupted.run_id == "run-process-recovery"
    assert interrupted.trace_id == "trace-process-recovery"
    assert lease is not None and lease.lease_owner == "process-a"
    interrupted_store.close()

    sleep(0.3)
    recovered = subprocess.run(
        [sys.executable, "-c", _PROCESS_CODE, "recover", runtime_path, checkpoint_path],
        capture_output=True,
        text=True,
        cwd=repository,
        timeout=30,
        check=False,
    )
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout.strip())
    assert result == {
        "task_id": "task-process-recovery",
        "run_id": "run-process-recovery",
        "trace_id": "trace-process-recovery",
        "pre_resume_status": "recovering",
        "recovered_ids": ["run-process-recovery"],
        "status": "completed",
        "context_events": 1,
    }
