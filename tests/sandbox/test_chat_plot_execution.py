from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.api.conversations import router
from backend.api.dependencies import get_conversation_store_service
from backend.models.execution_results import ExecutionResult
from backend.sandbox.workspace import SandboxWorkspaceManager
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.execution_image_service import image_response
from backend.services.execution_result_service import (
    load_execution_results,
    save_execution_results,
)
from backend.services.sandbox_debug_service import SandboxDebugError
from backend.services.script_plot_intent import wants_plot_execution
from backend.services.task_completion_verifier import verify_task_completion


def test_plot_routing_keeps_server_tool_availability():
    from backend.agent_tools.sandbox import build_python_sandbox_tool_definition
    from backend.services.agent_router_service import AgentDeterministicRouterService
    from backend.services.tool_capability_router import filter_capabilities

    tool = build_python_sandbox_tool_definition(SimpleNamespace()).spec
    router = AgentDeterministicRouterService()
    assert (
        router.route(user_message="写一个画爱心的脚本", tools=(tool,)).kind == "complex"
    )
    assert router.route(user_message="写一个画爱心的脚本", tools=()).kind != "complex"
    assert filter_capabilities((tool,), "解释这段并画爱心") == (tool,)


def test_native_plot_code_has_full_decision_budget():
    import json

    from backend.agent_tools.sandbox import build_python_sandbox_tool_definition
    from backend.services.agent_react_decision_service import AgentReActDecisionService

    code = "# plot details\n" * 500 + "print('plot')"
    calls = []

    class Client:
        def complete(self, **kwargs):
            raise AssertionError("native decision should use functions")

        def complete_tools(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                tool_calls=[
                    {
                        "id": "call-plot",
                        "function": {
                            "name": "python_execute",
                            "arguments": json.dumps({"code": code}),
                        },
                    }
                ],
                content="",
            )

    service = AgentReActDecisionService(
        SimpleNamespace(provider=SimpleNamespace(client=Client()))
    )
    decision = service.decide(
        iteration=1,
        tools=(build_python_sandbox_tool_definition(SimpleNamespace()).spec,),
        user_message="写一个画爱心的脚本",
        source_text="",
    )
    assert decision.arguments["code"] == code
    assert calls[0]["max_tokens"] == 8192
    assert "/output/heart.png" in calls[0]["messages"][0]["content"]


def test_source_counts_toward_artifact_budget(tmp_path):
    from dataclasses import replace

    from backend.sandbox.errors import SandboxOutputLimitError
    from backend.sandbox.policy import DEFAULT_SANDBOX_POLICY

    manager = SandboxWorkspaceManager(
        sandbox_root=tmp_path / "sandboxes",
        artifact_root=tmp_path / "artifacts",
        policy=replace(DEFAULT_SANDBOX_POLICY, max_output_files=1),
    )
    workspace = manager.create("sb_" + "c" * 32)
    (workspace.output_dir / "one.txt").write_text("output")
    with pytest.raises(SandboxOutputLimitError):
        manager.collect_outputs(workspace, source_code="print(1)")
    assert not (manager.artifact_root / workspace.sandbox_id).exists()


def test_resumed_runtime_emits_final_acceptance(monkeypatch):
    from backend.agent_core.events import AgentEventType
    from backend.agent_core.runtime import AgentRuntime
    from backend.agent_core.state import AgentState

    state = AgentState(session_id="plot", user_input="画爱心")
    report = {"status": "completed", "passed": 1, "total": 1}

    def resume(state, emit, **kwargs):
        state.browser_context["task_completion"] = report
        state.apply_response({"status": "completed", "output_text": "done"})
        return state

    runtime = AgentRuntime(workflow_adapter=SimpleNamespace(resume_with_events=resume))
    monkeypatch.setattr(runtime, "restore_checkpoint", lambda _: state)
    runtime.execute(state, resume=True)
    events = runtime.events
    assert events[-2].event_type == AgentEventType.TASK_VERIFICATION
    assert events[-2].payload == report
    assert events[-1].event_type == AgentEventType.AGENT_END


def test_snapshot_exposes_execution_receipts():
    from backend.agent_core.state import AgentState
    from backend.api.agent import get_agent_run_snapshot

    state = AgentState(session_id="plot", user_input="画爱心")
    state.tool_results = [
        {
            "tool_name": "python_execute",
            "data": {
                "sandbox_id": "sb_" + "a" * 32,
                "status": "succeeded",
                "exit_code": 0,
                "stdout": "saved image",
                "output_files": [],
            },
        }
    ]
    snapshot = get_agent_run_snapshot(
        state.run_id,
        SimpleNamespace(restore_checkpoint=lambda _: state),
        SimpleNamespace(get_run=lambda _: None, list_events=lambda _: []),
    )
    assert len(snapshot.execution_results) == 1
    assert snapshot.execution_results[0].stdout == "saved image"


@pytest.mark.parametrize(
    "text", ["写一个画爱心的脚本", "绘制折线图", "Draw a heart with Python"]
)
def test_plot_intent(text):
    assert wants_plot_execution(text)


@pytest.mark.parametrize(
    "text",
    [
        "写一个画爱心的脚本，只给代码",
        "画爱心但不要运行",
        "如何写一个画爱心的脚本",
        "draw a heart, code only",
        "how to draw a heart",
    ],
)
def test_non_execution_intent(text):
    assert not wants_plot_execution(text)


def test_preview_requires_decodable_raster():
    stream = BytesIO()
    Image.new("RGB", (20, 20), "red").save(stream, format="PNG")
    assert image_response("wrong.jpg", stream.getvalue()).media_type == "image/png"
    with pytest.raises(SandboxDebugError) as error:
        image_response("fake.png", b"<html><script>alert(1)</script></html>")
    assert error.value.status_code == 422


def test_image_filename_alone_cannot_pass_completion():
    state = SimpleNamespace(
        user_input="写一个画爱心的脚本",
        browser_context={},
        response={"output_text": "done"},
        tool_results=[
            {
                "tool_name": "python_execute",
                "verification": {"status": "passed"},
                "data": {
                    "status": "succeeded",
                    "output_files": [
                        {
                            "relative_path": "fake.png",
                            "size_bytes": 10,
                            "file_id": "fake",
                        }
                    ],
                },
            }
        ],
        plan=SimpleNamespace(steps=[], mode="react"),
        orchestration_status="",
        orchestration_results=[],
        orchestration_plan={},
        react=SimpleNamespace(status="completed"),
        evidence_sufficiency=None,
    )
    report = verify_task_completion(state)
    assert (
        next(
            item
            for item in report["criteria"]
            if item["criterion_id"] == "plot_artifact"
        )["status"]
        == "failed"
    )


def test_conversation_artifacts_are_bound_verified_and_restorable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AITRANSLATOR_DATA_DIR", str(tmp_path))
    store = ConversationStoreService(storage_path=tmp_path / "chat.sqlite3")
    exchange = store.begin_exchange(
        session_id="plot", user_message="画爱心", request_id=1, source_text=""
    )
    store.finalize_message(
        exchange.assistant_message_id, status="complete", content="生成了图片"
    )
    manager = SandboxWorkspaceManager()
    sid = "sb_" + "a" * 32
    workspace = manager.create(sid)
    Image.new("RGB", (20, 20), "red").save(workspace.output_dir / "heart.png")
    source = 'print("真实脚本")\n'
    files = manager.collect_outputs(workspace, source_code=source)
    source_id = next(file.file_id for file in files if file.is_source)
    receipt = ExecutionResult(
        sandbox_id=sid,
        status="succeeded",
        exit_code=0,
        output_files=[file.model_dump() for file in files],
        source_file_id=source_id,
    )
    save_execution_results(store.storage_path, exchange.assistant_message_id, [receipt])
    reopened = ConversationStoreService(storage_path=store.storage_path)
    assert load_execution_results(
        reopened.storage_path, exchange.assistant_message_id
    ) == [receipt]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_conversation_store_service] = lambda: reopened
    client = TestClient(app)
    prefix = f"/api/conversations/{exchange.conversation_id}/messages/{exchange.assistant_message_id}/executions/{sid}/files/"
    image = next(file for file in files if file.relative_path == "heart.png")
    response = client.get(prefix + image.file_id + "?inline=true")
    assert (
        response.status_code == 200 and response.headers["content-type"] == "image/png"
    )
    assert client.get(prefix + source_id).content == source.encode()
    assert (
        client.get(
            prefix.replace(exchange.assistant_message_id, exchange.user_message_id)
            + image.file_id
        ).status_code
        == 404
    )
    assert (
        client.get(prefix.replace(sid, "sb_" + "b" * 32) + image.file_id).status_code
        == 404
    )
    assert client.get(prefix + "sbo_" + "b" * 32).status_code == 404
    (manager.artifact_root / sid / image.relative_path).write_bytes(b"tampered")
    assert client.get(prefix + image.file_id).status_code == 409
    (manager.artifact_root / sid / image.relative_path).unlink()
    assert client.get(prefix + image.file_id).status_code == 410
    assert (
        client.get(f"/api/conversations/{exchange.conversation_id}").json()["messages"][
            -1
        ]["execution_results"][0]["source_file_id"]
        == source_id
    )
    reopened.delete(exchange.conversation_id)
    assert (
        load_execution_results(reopened.storage_path, exchange.assistant_message_id)
        == []
    )


@pytest.mark.docker_integration
def test_real_docker_plot_and_failed_source(tmp_path):
    from backend.agent_tools.base import AgentToolInvocationContext
    from backend.agent_tools.sandbox import (
        PythonExecuteArgs,
        build_python_sandbox_tool_definition,
    )
    from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
    from backend.sandbox.manager import SandboxManager
    from backend.services.sandbox_debug_artifacts import read_manifest_artifact

    runtime = DockerSandboxRuntime(timeout_seconds=30)
    assert runtime.health().available, (
        "Docker must be available for this acceptance test"
    )
    client = runtime._get_client()
    baseline = {
        container.id
        for container in client.containers.list(
            all=True, filters={"label": SANDBOX_LABEL}
        )
    }
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=tmp_path / "sandboxes", artifact_root=tmp_path / "artifacts"
        ),
    )
    tool = build_python_sandbox_tool_definition(manager)
    code = "import matplotlib.pyplot as plt\nimport numpy as np\nt=np.linspace(0,2*np.pi,500)\nplt.fill(16*np.sin(t)**3,13*np.cos(t)-5*np.cos(2*t)-2*np.cos(3*t)-np.cos(4*t),color='red')\nplt.axis('equal')\nplt.savefig('/output/heart.png')\nplt.close()\nprint('heart saved')\n"
    try:
        result = tool.executor(
            AgentToolInvocationContext(), PythonExecuteArgs(code=code)
        )
        assert result.data["status"] == "succeeded" and result.data["exit_code"] == 0
        assert "heart saved" in result.data["stdout"]
        assert len(result.data["verified_image_ids"]) == 1
        receipt = ExecutionResult.model_validate(result.data)
        _, content = read_manifest_artifact(
            receipt.sandbox_id,
            receipt.output_files,
            receipt.source_file_id,
            manager.artifact_root,
        )
        assert content == code.encode()
        _, png = read_manifest_artifact(
            receipt.sandbox_id,
            receipt.output_files,
            result.data["verified_image_ids"][0],
            manager.artifact_root,
        )
        with Image.open(BytesIO(png)) as image:
            assert image.width > 100 and image.height > 100
        failed = tool.executor(
            AgentToolInvocationContext(),
            PythonExecuteArgs(code="raise ValueError('intentional failure')"),
        )
        assert failed.data["exit_code"] != 0 and failed.data["source_file_id"]
        assert (
            not failed.data["verified_image_ids"]
            and "intentional failure" in failed.data["stderr"]
        )
        assert {
            container.id
            for container in client.containers.list(
                all=True, filters={"label": SANDBOX_LABEL}
            )
        } == baseline
    finally:
        manager.close()
