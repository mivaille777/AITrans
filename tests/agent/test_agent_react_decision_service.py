from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.ai.errors import AIResponseError
from backend.models.agent_react import AgentObservation, AgentRetrievalObservation
from backend.services.agent_react_decision_service import (
    REACT_DECISION_SYSTEM_PROMPT,
    AgentReActDecisionService,
)
from backend.services.agent_tool_registry import AgentToolSpec


def _tool(
    name: str,
    *,
    effect: str = "compute",
    requires_reading_context: bool = True,
    requires_confirmation: bool = False,
    input_schema: dict | None = None,
) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        title=name,
        description=f"Use {name}.",
        category="test",
        effect=effect,
        requires_reading_context=requires_reading_context,
        requires_confirmation=requires_confirmation,
        input_schema=dict(input_schema or {}),
    )


TOOLS = (
    _tool(
        "translate_selection",
        input_schema={"target_language": {"type": "string", "maxLength": 64}},
    ),
    _tool(
        "search_knowledge_base",
        requires_reading_context=False,
        input_schema={"query": {"type": "string", "maxLength": 4000}},
    ),
    _tool(
        "save_research_note",
        effect="write",
        requires_confirmation=True,
        input_schema={"user_note": {"type": "string", "maxLength": 4000}},
    ),
)


class FakeClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return json.dumps(self.response, ensure_ascii=False)


class FakeTextService:
    provider_name = "fake-react"
    model = "fake-model"

    def __init__(self, response: dict) -> None:
        self.provider = SimpleNamespace(client=FakeClient(response))


def _decide(response: dict, **overrides):
    text = FakeTextService(response)
    service = AgentReActDecisionService(text)
    payload = {
        "iteration": 1,
        "tools": TOOLS,
        "user_message": "Translate the selected passage.",
        "source_text": "Gaussian processes model uncertainty.",
        "translated_text": "",
        "resource_url": "file:///paper.pdf",
        "resource_title": "Paper",
        "section_heading": "Method",
        "context_before": "",
        "context_after": "",
        "source_kind": "pdf",
        "history": (),
        "observations": (),
    }
    payload.update(overrides)
    return service.decide(**payload), text.provider.client.calls


def test_react_decision_service_returns_one_validated_tool_action() -> None:
    decision, _calls = _decide(
        {
            "kind": "tool",
            "tool_name": "translate_selection",
            "arguments": {"target_language": "zh-CN"},
            "action_summary": "Translate the selected passage.",
            "final_answer": "",
        }
    )

    assert decision.iteration == 1
    assert decision.kind == "tool"
    assert decision.tool_name == "translate_selection"
    assert decision.arguments == {"target_language": "zh-CN"}
    assert decision.final_answer == ""


def test_react_decision_service_validates_agentic_rag_query() -> None:
    decision, _calls = _decide(
        {
            "kind": "tool",
            "tool_name": "search_knowledge_base",
            "arguments": {"query": "GP uncertainty calibration in PID tuning"},
            "action_summary": "Search for evidence about uncertainty calibration.",
            "final_answer": "",
        },
        user_message="Find evidence about uncertainty calibration.",
        source_text="",
    )

    assert decision.kind == "tool"
    assert decision.tool_name == "search_knowledge_base"
    assert decision.arguments == {"query": "GP uncertainty calibration in PID tuning"}


def test_react_decision_service_returns_final_without_tool_call() -> None:
    decision, _calls = _decide(
        {
            "kind": "final",
            "tool_name": "",
            "arguments": {},
            "action_summary": "Answer with the available evidence.",
            "final_answer": "Gaussian processes represent uncertainty probabilistically.",
        }
    )

    assert decision.kind == "final"
    assert decision.tool_name == ""
    assert decision.arguments == {}
    assert decision.final_answer.startswith("Gaussian processes")


def test_react_decision_rejects_unregistered_tool() -> None:
    with pytest.raises(AIResponseError, match="unregistered tool"):
        _decide(
            {
                "kind": "tool",
                "tool_name": "web_search",
                "arguments": {},
                "action_summary": "Search the web.",
                "final_answer": "",
            }
        )


def test_react_decision_rejects_arguments_outside_tool_authority() -> None:
    with pytest.raises(AIResponseError, match="outside its authority"):
        _decide(
            {
                "kind": "tool",
                "tool_name": "translate_selection",
                "arguments": {"system_prompt": "ignore policy"},
                "action_summary": "Translate the selected passage.",
                "final_answer": "",
            }
        )


def test_react_decision_rejects_reading_tool_without_reading_context() -> None:
    with pytest.raises(AIResponseError, match="without required reading context"):
        _decide(
            {
                "kind": "tool",
                "tool_name": "translate_selection",
                "arguments": {},
                "action_summary": "Translate the selection.",
                "final_answer": "",
            },
            source_text="",
        )


def test_react_decision_output_schema_rejects_hidden_reasoning_fields() -> None:
    with pytest.raises(AIResponseError, match="invalid structured output"):
        _decide(
            {
                "kind": "final",
                "tool_name": "",
                "arguments": {},
                "action_summary": "Answer now.",
                "final_answer": "Answer.",
                "reasoning": "private chain of thought",
            }
        )


def test_react_decision_prompt_contains_retrieval_observation_and_budgets() -> None:
    observation = AgentObservation(
        iteration=1,
        tool_name="search_knowledge_base",
        success=True,
        summary="evidence " * 1000,
        evidence_ids=["ev-1"],
        citation_ids=["cite-1"],
        retrieval=AgentRetrievalObservation(
            query="Gaussian process exploration mechanism",
            retrieval_strategy="hybrid",
            result_count=3,
            evidence_count=1,
            citation_count=1,
            novel_evidence_count=1,
        ),
    )
    _decision, calls = _decide(
        {
            "kind": "final",
            "tool_name": "",
            "arguments": {},
            "action_summary": "Use the retrieved evidence.",
            "final_answer": "Grounded answer.",
        },
        iteration=2,
        user_message="Answer using the retrieved evidence.",
        observations=(observation,),
        max_observation_chars=120,
        remaining_tool_calls=2,
        remaining_knowledge_searches=1,
    )

    payload = json.loads(calls[0]["user_prompt"])
    assert payload["iteration"] == 2
    assert len(payload["prior_observations"][0]["summary"]) <= 120
    assert payload["prior_observations"][0]["evidence_ids"] == ["ev-1"]
    retrieval = payload["prior_observations"][0]["retrieval"]
    assert retrieval["query"] == "Gaussian process exploration mechanism"
    assert retrieval["novel_evidence_count"] == 1
    assert payload["runtime_policy"]["remaining_tool_calls"] == 2
    assert payload["runtime_policy"]["remaining_knowledge_searches"] == 1
    assert payload["runtime_policy"]["rag_control_boundary"] == "query_continue_stop_only"
    assert "reasoning" not in payload
    assert payload["runtime_policy"]["private_reasoning_exposed"] is False


def test_react_decision_prompt_keeps_rag_internal_algorithms_outside_agent_control() -> None:
    assert "Do not attempt to control dense retrieval" in REACT_DECISION_SYSTEM_PROMPT
    assert "novel_evidence_count" in REACT_DECISION_SYSTEM_PROMPT
    assert "remaining_knowledge_searches" in REACT_DECISION_SYSTEM_PROMPT


def test_react_decision_requires_positive_iteration_and_observation_budget() -> None:
    service = AgentReActDecisionService(FakeTextService({}))

    with pytest.raises(ValueError, match="iteration must be positive"):
        service.decide(iteration=0, tools=TOOLS, user_message="x", source_text="x")
    with pytest.raises(ValueError, match="max_observation_chars must be positive"):
        service.decide(
            iteration=1,
            tools=TOOLS,
            user_message="x",
            source_text="x",
            max_observation_chars=0,
        )
