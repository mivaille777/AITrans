from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.ai.errors import AIResponseError
from backend.services.agent_multi_step_planner_service import AgentMultiStepPlannerService
from backend.services.agent_tool_registry import AgentToolSpec


def _tool(
    name: str,
    *,
    effect: str = "compute",
    requires_confirmation: bool = False,
    input_schema: dict | None = None,
) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        title=name,
        description=name,
        category="test",
        effect=effect,
        requires_reading_context=True,
        requires_confirmation=requires_confirmation,
        input_schema=dict(input_schema or {}),
    )


TOOLS = (
    _tool(
        "translate_selection",
        input_schema={"target_language": {"type": "string", "maxLength": 64}},
    ),
    _tool("explain_selection"),
    _tool("summarize_selection"),
    _tool(
        "save_research_note",
        effect="write",
        requires_confirmation=True,
        input_schema={"user_note": {"type": "string", "maxLength": 4000}},
    ),
)


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return json.dumps(self.payload, ensure_ascii=False)


class FakeTextService:
    provider_name = "fake-planner"
    model = "fake-model"

    def __init__(self, payload: dict) -> None:
        self.provider = SimpleNamespace(client=FakeClient(payload))


def _plan(payload: dict):
    return AgentMultiStepPlannerService(FakeTextService(payload)).plan(
        tools=TOOLS,
        max_steps=4,
        user_message="先翻译，然后解释一下",
        source_text="Gaussian processes model uncertainty.",
        translated_text="",
        resource_url="file:///paper.pdf",
        resource_title="Paper",
        section_heading="Method",
        context_before="",
        context_after="",
        source_kind="pdf",
        history=(),
    )


def test_multi_step_planner_returns_typed_bounded_plan() -> None:
    plan = _plan(
        {
            "goal": "Translate and explain the selected passage.",
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "translate_selection",
                    "arguments": {"target_language": "zh-CN"},
                    "depends_on": [],
                },
                {
                    "step_id": "step-2",
                    "tool_name": "explain_selection",
                    "arguments": {},
                    "depends_on": ["step-1"],
                },
            ],
        }
    )

    assert plan.mode == "multi_step"
    assert plan.current_step_id == "step-1"
    assert [step.tool_name for step in plan.steps] == [
        "translate_selection",
        "explain_selection",
    ]
    assert plan.steps[0].arguments == {"target_language": "zh-CN"}
    assert plan.steps[1].depends_on == ["step-1"]
    assert all(step.status == "pending" for step in plan.steps)


def test_multi_step_planner_rejects_unregistered_tools() -> None:
    with pytest.raises(AIResponseError, match="unregistered tool"):
        _plan(
            {
                "goal": "Use an unavailable capability.",
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool_name": "web_search",
                        "arguments": {},
                        "depends_on": [],
                    },
                    {
                        "step_id": "step-2",
                        "tool_name": "summarize_selection",
                        "arguments": {},
                        "depends_on": ["step-1"],
                    },
                ],
            }
        )


def test_multi_step_planner_requires_write_tool_to_be_final() -> None:
    with pytest.raises(AIResponseError, match="write tool"):
        _plan(
            {
                "goal": "Save and then explain.",
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool_name": "save_research_note",
                        "arguments": {"user_note": "Important"},
                        "depends_on": [],
                    },
                    {
                        "step_id": "step-2",
                        "tool_name": "explain_selection",
                        "arguments": {},
                        "depends_on": ["step-1"],
                    },
                ],
            }
        )


def test_multi_step_planner_rejects_forward_dependencies() -> None:
    with pytest.raises(AIResponseError, match="depends on unavailable step"):
        _plan(
            {
                "goal": "Invalid dependency ordering.",
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool_name": "translate_selection",
                        "arguments": {},
                        "depends_on": ["step-2"],
                    },
                    {
                        "step_id": "step-2",
                        "tool_name": "explain_selection",
                        "arguments": {},
                        "depends_on": [],
                    },
                ],
            }
        )
