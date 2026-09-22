from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import pytest

from backend.agent_core.exceptions import AgentToolTimeoutError
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolModel,
    EmptyToolResultData,
    typed_tool_definition,
)
from backend.models.agent_run import AgentRunRecord, AgentToolCallStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tasks import AgentTaskRecord
from backend.services.agent_run_store import AgentRunStore
from backend.services.agent_tool_execution_service import (
    AgentToolExecutionService,
    ToolExecutionRequest,
)


class Args(AgentToolModel):
    value: str


class Registry:
    def __init__(self, *, effect: str, executor):
        self.definition = typed_tool_definition(
            name="sample", title="Sample", description="Sample tool",
            category="test", effect=effect, requires_reading_context=False,
            requires_confirmation=effect == "write", args_model=Args,
            result_model=EmptyToolResultData, executor=executor,
            retry_policy="never" if effect == "write" else "safe",
        )

    def get_definition(self, name):
        return self.definition if name == "sample" else None

    def execute(self, name, **payload):
        result = self.definition.executor(None, self.definition.parse_args(payload))
        return self.definition.normalize_execution_result(result)


def result(effect: str) -> AgentToolExecutionResult:
    return AgentToolExecutionResult(tool_name="sample", output_text="done", effect=effect)


def durable_store(tmp_path) -> AgentRunStore:
    store = AgentRunStore(storage_path=tmp_path / "runtime.sqlite3")
    store.create_task_and_run(
        AgentTaskRecord(task_id="task-1", goal="Execute a tool"),
        AgentRunRecord(task_id="task-1", run_id="run-1", trace_id="trace-1",
                       runtime_profile=AgentRuntimeProfile.LONG_TASK),
    )
    return store


def test_write_is_claimed_once_by_100_concurrent_callers(tmp_path):
    store = durable_store(tmp_path)
    lock = Lock()
    physical = 0

    def write(_context, _args):
        nonlocal physical
        with lock:
            physical += 1
        sleep(0.05)
        return result("write")

    service = AgentToolExecutionService(Registry(effect="write", executor=write), store=store)

    def invoke(_index):
        return service.execute("sample", {"value": "same"},
                               control=AgentRunControl(), run_id="run-1", step_id="step-1",
                               write_confirmed=True)

    with ThreadPoolExecutor(max_workers=25) as pool:
        outputs = list(pool.map(invoke, range(100)))
    assert physical == 1
    assert all(output.output_text == "done" for output in outputs)


def test_failed_write_is_recorded_and_never_replayed(tmp_path):
    store = durable_store(tmp_path)
    count = 0

    def write(_context, _args):
        nonlocal count
        count += 1
        raise OSError("write outcome uncertain")

    service = AgentToolExecutionService(Registry(effect="write", executor=write), store=store)
    with pytest.raises(OSError):
        service.execute("sample", {"value": "same"}, control=AgentRunControl(),
                        run_id="run-1", step_id="step-1", write_confirmed=True)
    with pytest.raises(Exception, match="existing unresolved call"):
        service.execute("sample", {"value": "same"}, control=AgentRunControl(),
                        run_id="run-1", step_id="step-1", write_confirmed=True)
    assert count == 1


def test_unconfirmed_write_is_rejected_before_physical_execution():
    count = 0

    def write(_context, _args):
        nonlocal count
        count += 1
        return result("write")

    service = AgentToolExecutionService(Registry(effect="write", executor=write))
    with pytest.raises(Exception, match="requires confirmation"):
        service.execute("sample", {"value": "x"}, control=AgentRunControl())
    assert count == 0


def test_read_retries_transient_failure_only():
    count = 0

    def read(_context, _args):
        nonlocal count
        count += 1
        if count < 3:
            raise OSError("transient")
        return result("read")

    service = AgentToolExecutionService(
        Registry(effect="read", executor=read), retry_sleep=lambda _delay: None,
    )
    control = AgentRunControl(policy=AgentExecutionPolicy(max_safe_retries=2))
    assert service.execute("sample", {"value": "x"}, control=control).output_text == "done"
    assert count == 3


def test_timed_out_read_is_not_recorded_as_success(tmp_path):
    store = durable_store(tmp_path)

    def read(_context, _args):
        sleep(0.2)
        return result("read")

    service = AgentToolExecutionService(Registry(effect="read", executor=read), store=store)
    control = AgentRunControl(policy=AgentExecutionPolicy(
        total_timeout_seconds=1, tool_timeout_seconds=0.02,
    ))
    with pytest.raises(AgentToolTimeoutError):
        service.execute("sample", {"value": "x"}, control=control,
                        run_id="run-1", step_id="step-1")
    with store._connect() as connection:
        row = connection.execute("SELECT record_json FROM agent_tool_calls").fetchone()
    from backend.models.agent_run import AgentToolCallRecord
    assert AgentToolCallRecord.model_validate_json(row["record_json"]).status is AgentToolCallStatus.TIMED_OUT


def test_independent_reads_parallelize_but_dependencies_and_resources_serialize():
    lock = Lock()
    active = 0
    peak = 0

    def read(_context, _args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.03)
        with lock:
            active -= 1
        return result("read")

    service = AgentToolExecutionService(Registry(effect="read", executor=read))
    requests = [
        ToolExecutionRequest(step_id=str(index), tool_name="sample",
                             payload={"value": str(index)})
        for index in range(5)
    ]
    requests.append(ToolExecutionRequest(
        step_id="after", tool_name="sample", payload={"value": "after"},
        depends_on=("0", "1"),
    ))
    outputs = service.execute_many(requests, control=AgentRunControl())
    assert len(outputs) == 6
    assert 2 <= peak <= 4

    peak = 0
    service.execute_many([
        ToolExecutionRequest(step_id=str(index), tool_name="sample",
                             payload={"value": str(index)}, exclusive_resource="same")
        for index in range(3)
    ], control=AgentRunControl())
    assert peak == 1
