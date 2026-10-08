from dataclasses import asdict
from types import SimpleNamespace

import pytest

from backend.agent_core.state import AgentState
from backend.agent_tools.base import AgentToolExecutionResult, AgentToolModel, EmptyToolResultData, typed_tool_definition
from backend.models.agent_runtime import AgentPlanContext, AgentPlanStep
from backend.services.agent_tool_execution_service import AgentToolExecutionService
from backend.agent_core.reliability import AgentRunControl
from backend.services.tool_capability_router import filter_capabilities, requested_capabilities
from backend.services.tool_result_validator import ToolResultValidator
from backend.services.task_completion_verifier import apply_task_completion


def output(name, data=None, effect="compute", text="done"):
    return AgentToolExecutionResult(tool_name=name, output_text=text, effect=effect, data=data or {})


@pytest.mark.parametrize("data", [
    {"exit_code": 1, "status": "failed"},
    {"exit_code": 0, "timed_out": True},
    {"exit_code": None, "status": "cancelled"},
    {"exit_code": 0, "oom_killed": True},
])
def test_fake_process_success_is_rejected(data):
    result = ToolResultValidator().verify("python_execute", {}, output("python_execute", data))
    assert result.status == "failed"
    assert result.error_code == "result_verification_failed"


def test_false_write_receipt_fails_readback():
    verifier = ToolResultValidator(research=SimpleNamespace(get=lambda _id: None))
    result = verifier.verify("save_research_note", {}, output("save_research_note", {"note_id": "missing"}, "write"))
    assert result.verification["status"] == "failed"


def test_note_readback_checks_content():
    verifier = ToolResultValidator(research=SimpleNamespace(get=lambda _id: SimpleNamespace(user_note="old")))
    result = verifier.verify("update_research_note", {"note_id": "n1", "user_note": "new"}, output("update_research_note", {}, "write"))
    assert result.status == "failed"


def test_unknown_write_is_never_reported_verified():
    result = ToolResultValidator().verify("unsupported_write", {}, output("unsupported_write", {}, "write"))
    assert result.status == "unknown"


def test_failed_tool_overrides_model_claim_and_prevents_export():
    from backend.services.markdown_export_service import run_markdown_document
    state = AgentState(session_id="reliability", user_input="运行测试并导出 Markdown")
    result = ToolResultValidator().verify("python_execute", {}, output("python_execute", {"exit_code": 1}))
    state.record_tool_result(asdict(result))
    state.apply_response({"status": "completed", "output_text": "所有测试通过，任务已完成。"})
    report = apply_task_completion(state)
    assert report["status"] == "partial"
    assert "所有测试通过" not in state.response["output_text"]
    assert run_markdown_document(state) is None


def test_model_cannot_skip_requested_execution():
    state = AgentState(session_id="reliability", user_input="请运行 Python 计算 2+2")
    state.apply_response({"status": "completed", "output_text": "4"})
    report = apply_task_completion(state)
    assert report["status"] != "completed"
    assert any(item["criterion_id"] == "process_requested" and item["status"] == "failed" for item in report["criteria"])


def test_missing_plan_step_remains_incomplete():
    state = AgentState(session_id="reliability", user_input="inspect")
    state.apply_route({"kind": "complex", "source": "planner"})
    state.apply_multi_step_plan(AgentPlanContext(mode="multi_step", steps=[AgentPlanStep(step_id="s1", tool_name="read_workspace_file")]).model_dump())
    state.apply_response({"status": "completed", "output_text": "done"})
    assert apply_task_completion(state)["status"] == "partial"


def test_markdown_evidence_is_generated_not_saved():
    from backend.services.markdown_export_service import markdown_document
    data = markdown_document("```markdown\n# Hello\n```", "hello.md").model_dump()
    result = ToolResultValidator().verify("export_markdown_document", {"markdown": "```markdown\n# Hello\n```"}, output("export_markdown_document", data))
    assert result.status == "success"
    assert result.verification["checks"][0]["evidence"]["delivery_state"] == "generated"


def test_scope_violation_cannot_pass_result_validation():
    result = ToolResultValidator().verify("search_knowledge_base", {"knowledge_document_ids": ["allowed"]}, output("search_knowledge_base", {"results": [{"document_id": "outside"}]}))
    assert result.status == "failed"


def test_empty_scope_does_not_grant_global_access():
    result = ToolResultValidator().verify("search_knowledge_base", {}, output("search_knowledge_base", {"results": [{"document_id": "outside"}]}))
    assert result.status == "failed"


def test_single_step_uses_verified_receipt_without_step_id():
    state = AgentState(session_id="single", user_input="运行 Python")
    state.apply_plan({"action": "tool", "tool_name": "python_execute"})
    state.record_tool_result(asdict(ToolResultValidator().verify("python_execute", {}, output("python_execute", {"exit_code": 0}))))
    state.apply_response({"status": "completed", "output_text": "4"})
    assert apply_task_completion(state)["status"] == "completed"


@pytest.mark.parametrize("offset,expected", [(4, "partial"), (3, "completed")])
def test_full_file_read_requires_contiguous_verified_pages(offset, expected):
    state = AgentState(session_id="pages", user_input="读取工作区文件全文", browser_context={"filesystem_workspace_id": "w"})
    for begin, end in [(0, 3), (offset, 6)]:
        state.record_tool_result({"tool_name": "read_workspace_file", "verification": {"status": "passed"},
            "data": {"relative_path": "file.md", "offset": begin, "next_offset": end, "total_chars": 6}})
    state.apply_response({"status": "completed", "output_text": "summary"})
    assert apply_task_completion(state)["status"] == expected


def test_research_required_failure_preserves_acceptance_gate():
    state = AgentState(session_id="research", user_input="研究比较")
    state.apply_orchestration(lane="research", status="partial", scope={},
        plan={"tasks": [{"task_id": "required", "required": True}, {"task_id": "optional", "required": False}]},
        results=[{"task_id": "required", "status": "failed", "unmet_requirements": ["source"]}])
    state.apply_response({"status": "completed", "output_text": "研究全部完成。"})
    report = apply_task_completion(state)
    assert report["status"] == "partial"
    assert "研究全部完成" not in state.response["output_text"]
    assert not any(item["criterion_id"] == "research:optional" for item in report["criteria"])


@pytest.mark.parametrize("message", ["如何运行 Python？", "不要运行代码", "怎么导出 Markdown？", "把‘执行’翻译成英文"])
def test_non_execution_text_does_not_require_compute(message):
    assert "compute" not in requested_capabilities(message)


def test_router_only_returns_registered_capabilities():
    tools = [SimpleNamespace(name="export_markdown_document", category="writing"), SimpleNamespace(name="command_execute", category="sandbox")]
    assert [item.name for item in filter_capabilities(tools, "导出为 Markdown 文档")] == ["export_markdown_document"]


def test_readback_unavailable_retains_unknown_receipt_without_replaying(tmp_path):
    from tests.agent.test_agent_tool_execution import Registry, durable_store, result
    count = 0
    def execute(_context, _args):
        nonlocal count
        count += 1
        return result("write")
    registry = Registry(effect="write", executor=execute)
    registry.verify_result = lambda *_: (_ for _ in ()).throw(OSError("readback unavailable"))
    service = AgentToolExecutionService(registry, store=durable_store(tmp_path))
    for _ in range(2):
        receipt = service.execute("sample", {"value": "same"}, control=AgentRunControl(), run_id="run-1", step_id="s1", write_confirmed=True)
        assert receipt.status == "unknown"
    assert count == 1


def test_configured_schema_does_not_expose_hidden_context():
    from pydantic import Field
    from backend.services.tool_configuration import metadata_definition
    class Args(AgentToolModel):
        query: str
        conversation_id: str = ""
    class Planner(AgentToolModel):
        query: str = Field(min_length=1)
    definition = typed_tool_definition(name="sample", title="Sample", description="sample", category="test", effect="read",
        requires_reading_context=False, requires_confirmation=False, args_model=Args, planner_args_model=Planner,
        result_model=EmptyToolResultData, executor=lambda *_: None)
    configured = metadata_definition(definition, {"title": "Configured"})
    assert set(configured.spec.input_schema) == {"query"}
    with pytest.raises(ValueError):
        configured.spec.validate_planner_arguments({"conversation_id": "forged"})
    with pytest.raises(ValueError):
        configured.spec.validate_planner_arguments({"query": ""})
    with pytest.raises(ValueError):
        configured.spec.validate_planner_arguments({})


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_native_model_receives_actual_validation_failure(status):
    import json
    from backend.models.agent_react import AgentReActDecision
    from backend.services.agent_react_decision_service import AgentReActDecisionService
    calls = []
    def complete_tools(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(tool_calls=[], content="Finished")
    service = AgentReActDecisionService()
    service._decide_native(client=SimpleNamespace(complete_tools=complete_tools), iteration=2, tools=[], prompt="request",
        spec=SimpleNamespace(system_prompt="prompt", temperature=0), payload={
            "native_decisions": [AgentReActDecision(iteration=1, kind="tool", tool_name="python_execute", native_tool_call_id="native-1")],
            "native_results": [{"step_id": "react-1", "status": status, "verification": {"status": status}, "data": {"exit_code": 1}}]})
    receipt = json.loads(next(item["content"] for item in calls[0]["messages"] if item["role"] == "tool"))
    assert receipt["ok"] is False and receipt["status"] == status
    assert receipt["verification"]["status"] == status


def test_verification_timeout_keeps_receipt_and_never_replays_write(tmp_path):
    from time import sleep
    from backend.agent_core.reliability import AgentExecutionPolicy
    from tests.agent.test_agent_tool_execution import Registry, durable_store, result
    executions = []
    registry = Registry(effect="write", executor=lambda *_: (executions.append(1), result("write"))[1])
    registry.verify_result = lambda *_: (sleep(0.1), result("write"))[1]
    service = AgentToolExecutionService(registry, store=durable_store(tmp_path))
    receipt = service.execute("sample", {"value": "x"}, run_id="run-1", step_id="s1", write_confirmed=True,
        control=AgentRunControl(policy=AgentExecutionPolicy(tool_timeout_seconds=0.02)))
    assert receipt.status == "unknown" and executions == [1]


def test_exception_emits_failed_task_acceptance():
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_core.events import AgentEventType
    runtime = AgentRuntime(planner=lambda _: (_ for _ in ()).throw(RuntimeError("broken")))
    with pytest.raises(RuntimeError):
        runtime.execute(AgentState(session_id="error", user_input="hello"))
    report = next(event.payload for event in runtime.events if event.event_type == AgentEventType.TASK_VERIFICATION)
    assert report["status"] == "failed" and report["passed"] == 0


def test_verification_metrics_survive_redacted_trace_storage(tmp_path):
    from backend.agent_core.events import AgentEvent, AgentEventType
    from backend.services.agent_trace_store_service import AgentTraceStoreService
    from backend.evaluation.agent_evaluator import derive_agent_trajectory_metrics
    state = AgentState(session_id="metrics", user_input="private")
    store = AgentTraceStoreService(storage_path=tmp_path / "trace.sqlite3")
    store.record(state, (
        AgentEvent(event_type=AgentEventType.TOOL_VERIFICATION, run_id=state.run_id, trace_id=state.trace_id,
            payload={"status": "failed", "checks": [{"detail": "PRIVATE CONTENT"}]}),
        AgentEvent(event_type=AgentEventType.TASK_VERIFICATION, run_id=state.run_id, trace_id=state.trace_id,
            payload={"status": "partial", "passed": 1, "total": 2, "criteria": [{"evidence": "PRIVATE CONTENT"}]}),
    ))
    events = store.list_events(state.run_id)
    assert "PRIVATE CONTENT" not in repr(events)
    metrics = derive_agent_trajectory_metrics(events)
    assert metrics.tool_verification_count == 1 and metrics.tool_verification_pass_count == 0
    assert metrics.final_task_completion_status == "partial"
    assert metrics.required_acceptance_count == 2 and metrics.required_acceptance_pass_count == 1
