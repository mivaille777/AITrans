from types import SimpleNamespace

from backend.agent_core.events import AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult


class FakeProductAgentService:
    def __init__(self) -> None:
        self.payload = None

    def run(self, **payload):
        self.payload = payload
        return SimpleNamespace(
            status="completed",
            plan=AgentPlan(
                action="tool",
                tool_name="translate_selection",
                user_visible_reason="Translate the selected text.",
                arguments={"target_language": "zh-CN"},
            ),
            output_text="高斯过程",
            provider="fake-provider",
            model="fake-model",
            request_id=11,
            tool_result=AgentToolExecutionResult(
                tool_name="translate_selection",
                output_text="高斯过程",
                effect="compute",
                provider="fake-provider",
                model="fake-model",
                request_id=11,
                data={"target_language": "zh-CN"},
            ),
        )


def test_product_runtime_adapter_maps_existing_service_result_to_agent_state():
    service = FakeProductAgentService()
    adapter = ProductAgentRuntimeAdapter(service)
    state = AgentState(
        session_id="session-1",
        user_input="Translate this",
        selected_text="Gaussian Process",
        browser_context={
            "target_language": "zh-CN",
            "resource_title": "Control Paper",
            "request_id": 11,
        },
    )

    result = adapter(state)

    assert service.payload["user_message"] == "Translate this"
    assert service.payload["source_text"] == "Gaussian Process"
    assert service.payload["resource_title"] == "Control Paper"
    assert result.intent == "translate_selection"
    assert result.ui_mode == "translation"
    assert result.tool_calls == [
        {
            "name": "translate_selection",
            "arguments": {"target_language": "zh-CN"},
        }
    ]
    assert result.tool_results[0]["output_text"] == "高斯过程"
    assert result.response["output_text"] == "高斯过程"
    assert result.response["status"] == "completed"


def test_product_runtime_adapter_preserves_explicit_filesystem_workspace_context():
    service = FakeProductAgentService()
    adapter = ProductAgentRuntimeAdapter(service)
    files = [{"relative_path": "input/data.csv", "size_bytes": 42}]

    adapter(
        AgentState(
            session_id="session-1",
            user_input="Read the selected CSV",
            browser_context={
                "filesystem_workspace_id": "fsw_opaque-id",
                "filesystem_workspace_files": files,
            },
        )
    )

    assert service.payload["filesystem_workspace_id"] == "fsw_opaque-id"
    assert service.payload["filesystem_workspace_files"] == files


def test_agent_runtime_emits_tool_events_for_product_workflow():
    service = FakeProductAgentService()
    runtime = AgentRuntime(
        context_provider=lambda state: {
            **state.browser_context,
            "resource_title": "Control Paper",
        },
        workflow_adapter=ProductAgentRuntimeAdapter(service),
    )
    observed = []

    result = runtime.execute(
        AgentState(
            session_id="session-1",
            user_input="Translate this",
            selected_text="Gaussian Process",
            browser_context={"target_language": "zh-CN", "request_id": 11},
        ),
        event_sink=observed.append,
    )

    assert result.response["output_text"] == "高斯过程"
    assert observed == runtime.events
    assert [event.event_type for event in runtime.events] == [
        AgentEventType.AGENT_START,
        AgentEventType.CONTEXT_READY,
        AgentEventType.PLAN_READY,
        AgentEventType.TOOL_CALL,
        AgentEventType.TOOL_RESULT,
        AgentEventType.AGENT_END,
    ]
