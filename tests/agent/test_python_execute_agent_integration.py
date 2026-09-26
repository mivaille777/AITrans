from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.models.agent_runtime import AgentRouteDecision
from backend.sandbox.docker_runtime import (
    SANDBOX_ID_LABEL,
    DockerSandboxRuntime,
)
from backend.sandbox.manager import SandboxManager
from backend.sandbox.models import SandboxExecutionResult
from backend.sandbox.workspace import SandboxWorkspaceManager
from backend.services.agent_router_service import AgentDeterministicRouterService
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.product_agent_service import ProductAgentService


class FakeSandboxManager:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.stdout = "285\n"

    def execute_python(self, code: str) -> SandboxExecutionResult:
        self.calls.append(code)
        return SandboxExecutionResult(
            sandbox_id="sb_integration",
            status="succeeded",
            exit_code=0,
            stdout=self.stdout,
            stderr="",
            duration_ms=21,
            stdout_bytes=4,
            stderr_bytes=0,
            image="aitrans-python-sandbox:v1",
        )


class FakeChatService:
    provider_name = "fake-chat"
    model = "fake-model"
    prompt_id = "fake-chat@test"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            output_text="The result is 285.",
            provider=self.provider_name,
            model=self.model,
            request_id=kwargs.get("request_id", 0),
        )


class CapturingSemanticRouter:
    provider_name = "fake-router"
    model = "fake-model"
    prompt_id = "fake-router@test"

    def __init__(self) -> None:
        self.catalogs: list[set[str]] = []

    def route(self, *, tools, **_kwargs):
        self.catalogs.append({tool.name for tool in tools})
        return AgentRouteDecision(
            kind="answer",
            source="semantic_router",
            intent="answer",
            user_visible_reason="Answer without an available Python capability.",
        )


def _payload(**extra):
    return {
        "session_id": "sandbox-agent-test",
        "user_message": "用 Python 计算 sum(i*i for i in range(10))",
        "source_text": "",
        "translated_text": "",
        "source_language": "auto",
        "target_language": "zh-CN",
        "resource_url": "",
        "resource_title": "",
        "section_heading": "",
        "context_before": "",
        "context_after": "",
        "source_kind": "desktop",
        "context_mode": "general",
        **extra,
    }


def test_explicit_python_request_executes_and_trace_contains_only_summaries() -> None:
    manager = FakeSandboxManager()
    chat = FakeChatService()
    registry = AgentToolRegistry(sandbox_manager=manager)
    service = ProductAgentService(registry=registry, chat_service=chat)
    events: list[tuple[str, dict[str, object]]] = []
    source = "print(sum(i*i for i in range(10)))"
    # Use a unique output sentinel to prove the lifecycle trace does not
    # persist returned content.
    manager.stdout = "PRIVATE_STDOUT_SENTINEL"

    result = service.run(
        **_payload(enabled_tools=["python_execute"]),
        event_sink=lambda event_type, payload: events.append((event_type, payload)),
    )

    assert result.status == "completed"
    assert result.route is not None and result.route.tool_name == "python_execute"
    assert manager.calls == [source]
    assert chat.calls
    synthesis_context = str(chat.calls[0]["tool_context"])
    assert "PRIVATE_STDOUT_SENTINEL" in synthesis_context
    assert result.output_text == "The result is 285."

    plan_event = next(payload for name, payload in events if name == "plan_ready")
    tool_call = next(payload for name, payload in events if name == "tool_call")
    tool_result = next(payload for name, payload in events if name == "tool_result")
    expected_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert plan_event["arguments"] == {
        "code_sha256": expected_digest,
        "code_chars": len(source),
    }
    assert tool_call["arguments"] == plan_event["arguments"]
    assert tool_result["data"]["sandbox_id"] == "sb_integration"
    assert tool_result["data"]["duration_ms"] == 21
    assert tool_result["data"]["output_file_count"] == 0
    assert tool_result["output_text"] == ""

    persisted = json.dumps(events, ensure_ascii=False)
    assert source not in persisted
    assert "PRIVATE_STDOUT_SENTINEL" not in persisted
    assert "C:\\Users\\" not in persisted
    assert "/workspace/" not in persisted


def test_enabled_tools_hides_python_from_semantic_planner_when_not_selected() -> None:
    manager = FakeSandboxManager()
    semantic = CapturingSemanticRouter()
    service = ProductAgentService(
        registry=AgentToolRegistry(sandbox_manager=manager),
        chat_service=FakeChatService(),
        semantic_router=semantic,
    )

    route, _metadata = service.resolve_route(
        **_payload(enabled_tools=["translate_selection"])
    )

    assert route.kind == "answer"
    assert semantic.catalogs == [{"translate_selection"}]
    assert "python_execute" not in semantic.catalogs[0]


def test_python_deterministic_route_is_narrow_and_extracts_code() -> None:
    registry = AgentToolRegistry(sandbox_manager=FakeSandboxManager())
    tools = registry.list_tools()
    router = AgentDeterministicRouterService()

    route = router.route(
        user_message="用 Python 计算 sum(i*i for i in range(10))", tools=tools
    )
    code_route = router.route(
        user_message="执行这段 Python 代码：\n```python\nprint(2 + 2)\n```",
        tools=tools,
    )
    english_route = router.route(
        user_message="Calculate this with Python: sum(i for i in range(3))",
        tools=tools,
    )
    gil_route = router.route(user_message="给我介绍 Python 的 GIL", tools=tools)

    assert route.tool_name == "python_execute"
    assert route.arguments == {"code": "print(sum(i*i for i in range(10)))"}
    assert code_route.tool_name == "python_execute"
    assert code_route.arguments == {"code": "print(2 + 2)"}
    assert english_route.arguments == {"code": "print(sum(i for i in range(3)))"}
    assert gil_route.kind == "unresolved"


@pytest.mark.docker_integration
def test_real_docker_python_request_flows_through_agent_and_cleans_up(tmp_path) -> None:
    runtime = DockerSandboxRuntime()
    health = runtime.health()
    if not health.available:
        runtime.close()
        pytest.skip(f"Docker sandbox unavailable: {health.error_code}")

    host_root = (
        Path(tempfile.gettempdir()) / "aitrans-sandbox-agent-tests" / uuid4().hex
    )
    manager = SandboxManager(
        runtime,
        SandboxWorkspaceManager(
            sandbox_root=host_root / "sandboxes",
            artifact_root=tmp_path / "artifacts",
        ),
    )
    chat = FakeChatService()
    service = ProductAgentService(
        registry=AgentToolRegistry(sandbox_manager=manager),
        chat_service=chat,
    )
    try:
        result = service.run(
            **_payload(enabled_tools=["python_execute"]),
        )
        assert result.status == "completed"
        assert result.route is not None and result.route.tool_name == "python_execute"
        assert result.tool_result is not None
        assert result.tool_result.data["stdout"].strip() == "285"
        assert result.output_text == "The result is 285."
        containers = runtime._get_client().containers.list(
            all=True,
            filters={
                "label": f"{SANDBOX_ID_LABEL}={result.tool_result.data['sandbox_id']}"
            },
        )
        assert containers == []
    finally:
        manager.close()
        shutil.rmtree(host_root, ignore_errors=True)
