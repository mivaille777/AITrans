from __future__ import annotations

from time import sleep
from types import SimpleNamespace

import pytest

from backend.agent_core.exceptions import AgentToolTimeoutError
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.product_agent_service import ProductAgentService


TRANSLATE_TOOL = AgentToolSpec(
    name="translate_selection",
    title="Translate selection",
    description="Translate the current selection.",
    category="translation",
    effect="compute",
    requires_reading_context=True,
    requires_confirmation=False,
    input_schema={},
)
WRITE_TOOL = AgentToolSpec(
    name="save_research_note",
    title="Save research note",
    description="Persist the current selection.",
    category="research",
    effect="write",
    requires_reading_context=True,
    requires_confirmation=True,
    input_schema={},
)


class FakePlanner:
    def __init__(self, plan: AgentPlan) -> None:
        self.plan_result = plan

    def plan(self, **_kwargs):
        return self.plan_result


class FakeRegistry:
    def __init__(
        self,
        spec: AgentToolSpec,
        *,
        failures: int = 0,
        delay_seconds: float = 0.0,
    ) -> None:
        self.spec = spec
        self.failures = failures
        self.delay_seconds = delay_seconds
        self.executions: list[tuple[str, dict]] = []

    def list_tools(self):
        return (self.spec,)

    def get_tool(self, name: str):
        return self.spec if name == self.spec.name else None

    def execute(self, name: str, **payload):
        self.executions.append((name, payload))
        if self.delay_seconds > 0:
            sleep(self.delay_seconds)
        if len(self.executions) <= self.failures:
            raise OSError("temporary provider failure")
        return AgentToolExecutionResult(
            tool_name=name,
            output_text="工具结果",
            effect=self.spec.effect,
            provider="fake-tool",
            model="fake-model",
            request_id=payload.get("request_id", 0),
            data={"grounded": True},
        )


class FakeChatService:
    def send(self, **kwargs):
        return SimpleNamespace(
            output_text="最终回答",
            provider="fake-chat",
            model="fake-model",
            request_id=kwargs.get("request_id", 0),
        )


def payload(**overrides):
    return {
        "session_id": "session-live",
        "user_message": "Translate this",
        "source_text": "Gaussian Process",
        "translated_text": "",
        "source_language": "en",
        "target_language": "zh-CN",
        "resource_url": "file:///paper.pdf",
        "resource_title": "Paper",
        "section_heading": "Method",
        "context_before": "Before",
        "context_after": "After",
        "source_kind": "pdf_uia",
        "request_id": 19,
        **overrides,
    }


def service_for(spec: AgentToolSpec, registry: FakeRegistry) -> ProductAgentService:
    return ProductAgentService(
        registry=registry,
        chat_service=FakeChatService(),
        planner=FakePlanner(
            AgentPlan(
                action="tool",
                tool_name=spec.name,
                user_visible_reason="Use the bounded tool.",
            )
        ),
    )


def test_product_agent_emits_phase_timings_at_execution_boundaries() -> None:
    registry = FakeRegistry(TRANSLATE_TOOL)
    service = service_for(TRANSLATE_TOOL, registry)
    events: list[tuple[str, dict]] = []

    result = service.run(
        event_sink=lambda event_type, data: events.append((event_type, data)),
        **payload(),
    )

    assert result.status == "completed"
    assert [event_type for event_type, _ in events] == [
        "plan_ready",
        "tool_call",
        "tool_result",
        "tool_verification",
        "synthesis_ready",
    ]
    assert events[0][1]["duration_ms"] >= 0
    assert events[2][1]["duration_ms"] >= 0
    assert events[3][1]["status"] == "passed"
    assert events[4][1]["duration_ms"] >= 0
    assert registry.executions[0][0] == "translate_selection"


def test_safe_compute_tool_retries_once_after_transient_failure() -> None:
    registry = FakeRegistry(TRANSLATE_TOOL, failures=1)
    service = service_for(TRANSLATE_TOOL, registry)
    events: list[tuple[str, dict]] = []
    control = AgentRunControl(
        policy=AgentExecutionPolicy(max_safe_retries=1),
    )

    result = service.run(
        event_sink=lambda event_type, data: events.append((event_type, data)),
        control=control,
        **payload(),
    )

    assert result.status == "completed"
    assert len(registry.executions) == 2
    retry = next(data for event_type, data in events if event_type == "retry")
    assert retry["attempt"] == 2
    assert retry["max_attempts"] == 2
    assert "temporary provider failure" in retry["reason"]


def test_hard_compute_timeout_is_not_automatically_retried() -> None:
    registry = FakeRegistry(TRANSLATE_TOOL, delay_seconds=0.1)
    service = service_for(TRANSLATE_TOOL, registry)
    events: list[tuple[str, dict]] = []
    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=1.0,
            tool_timeout_seconds=0.01,
            max_safe_retries=3,
        ),
    )

    with pytest.raises(AgentToolTimeoutError):
        service.run(
            event_sink=lambda event_type, data: events.append((event_type, data)),
            control=control,
            **payload(),
        )

    assert len(registry.executions) == 1
    assert "retry" not in {event_type for event_type, _ in events}


def test_product_agent_confirmation_stops_before_live_tool_result() -> None:
    registry = FakeRegistry(WRITE_TOOL)
    service = service_for(WRITE_TOOL, registry)
    events: list[tuple[str, dict]] = []

    result = service.run(
        event_sink=lambda event_type, data: events.append((event_type, data)),
        **payload(user_message="Save this note"),
    )

    assert result.status == "confirmation_required"
    assert [event_type for event_type, _ in events] == ["plan_ready", "tool_call"]
    assert registry.executions == []


def test_confirmed_write_tool_is_never_automatically_retried() -> None:
    registry = FakeRegistry(WRITE_TOOL, failures=1)
    service = service_for(WRITE_TOOL, registry)
    events: list[tuple[str, dict]] = []
    control = AgentRunControl(
        policy=AgentExecutionPolicy(max_safe_retries=3),
    )

    with pytest.raises(OSError, match="temporary provider failure"):
        service.run(
            event_sink=lambda event_type, data: events.append((event_type, data)),
            control=control,
            **payload(
                user_message="Save this note",
                confirmed_write_tools=["save_research_note"],
            ),
        )

    assert len(registry.executions) == 1
    assert "retry" not in {event_type for event_type, _ in events}
