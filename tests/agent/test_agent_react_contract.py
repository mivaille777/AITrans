from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agent_core.events import AgentEventType
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.state import AgentState
from backend.models.agent_react import (
    AgentObservation,
    AgentRetrievalObservation,
    AgentReActContext,
    AgentReActDecision,
)


def test_react_tool_decision_is_strict_and_contains_no_reasoning_field() -> None:
    decision = AgentReActDecision(
        iteration=1,
        kind="tool",
        tool_name="search_knowledge",
        arguments={"query": "safe Bayesian optimization"},
        action_summary="Search for supporting evidence.",
    )

    assert decision.tool_name == "search_knowledge"
    assert decision.arguments == {"query": "safe Bayesian optimization"}
    assert "thought" not in AgentReActDecision.model_fields
    assert "reasoning" not in AgentReActDecision.model_fields

    with pytest.raises(ValidationError, match="tool decisions require tool_name"):
        AgentReActDecision(iteration=1, kind="tool")

    with pytest.raises(ValidationError):
        AgentReActDecision(
            iteration=1,
            kind="tool",
            tool_name="search_knowledge",
            thought="private reasoning must never enter the contract",
        )


def test_react_final_decision_cannot_smuggle_a_tool_call() -> None:
    decision = AgentReActDecision(
        iteration=2,
        kind="final",
        action_summary="Enough evidence is available to answer.",
        final_answer="Grounded answer.",
    )

    assert decision.kind == "final"
    assert decision.tool_name == ""
    assert decision.arguments == {}

    with pytest.raises(ValidationError, match="final decisions cannot include tool_name"):
        AgentReActDecision(
            iteration=2,
            kind="final",
            tool_name="save_research_note",
        )


def test_observation_is_compact_and_normalizes_reference_ids() -> None:
    observation = AgentObservation(
        iteration=1,
        tool_name="search_knowledge",
        success=True,
        summary="  Found supporting passages.  ",
        evidence_ids=[" ev-1 ", "", "ev-2"],
        citation_ids=[" cite-1 "],
    )

    assert observation.observation_id.startswith("observation-")
    assert observation.summary == "Found supporting passages."
    assert observation.evidence_ids == ["ev-1", "ev-2"]
    assert observation.citation_ids == ["cite-1"]


def test_retrieval_observation_is_scoped_to_knowledge_tool() -> None:
    retrieval = AgentRetrievalObservation(
        query="  GP global exploration  ",
        retrieval_strategy=" hybrid ",
        result_count=4,
        evidence_count=2,
        citation_count=2,
        novel_evidence_count=1,
        fallback_reason=" reranker unavailable ",
    )
    observation = AgentObservation(
        iteration=1,
        tool_name="search_knowledge_base",
        success=True,
        retrieval=retrieval,
    )

    assert observation.retrieval is not None
    assert observation.retrieval.query == "GP global exploration"
    assert observation.retrieval.retrieval_strategy == "hybrid"
    assert observation.retrieval.fallback_reason == "reranker unavailable"

    with pytest.raises(ValidationError, match="only valid for knowledge search"):
        AgentObservation(
            iteration=1,
            tool_name="translate_selection",
            success=True,
            retrieval=retrieval,
        )
    with pytest.raises(ValidationError, match="cannot exceed evidence_count"):
        AgentRetrievalObservation(evidence_count=1, novel_evidence_count=2)


def test_agent_state_keeps_react_context_separate_from_existing_plan_contract() -> None:
    state = AgentState(user_input="translate this")

    assert state.react == AgentReActContext()
    assert state.react.status == "idle"

    state.apply_plan(
        {
            "action": "tool",
            "tool_name": "translate_selection",
            "arguments": {"target_language": "zh-CN"},
        }
    )

    assert state.plan.mode == "single_step"
    assert state.plan.steps[0].tool_name == "translate_selection"
    assert state.react.status == "idle"
    assert state.react.decisions == []
    assert state.react.observations == []


def test_agent_state_records_structured_react_decision_and_observation() -> None:
    state = AgentState(user_input="search and explain").start_react()

    state.record_react_decision(
        {
            "iteration": 1,
            "kind": "tool",
            "tool_name": "search_knowledge",
            "arguments": {"query": "PID tuning"},
            "action_summary": "Search the knowledge base.",
        }
    )
    state.record_react_observation(
        {
            "iteration": 1,
            "tool_name": "search_knowledge",
            "success": True,
            "summary": "Found four relevant chunks.",
            "evidence_ids": ["ev-1", "ev-2"],
        }
    )

    assert state.react.status == "running"
    assert state.react.iteration == 1
    assert state.react.last_decision == state.react.decisions[-1]
    assert state.react.observations[-1].evidence_ids == ["ev-1", "ev-2"]

    with pytest.raises(ValueError, match="must advance monotonically"):
        state.record_react_decision(
            {
                "iteration": 1,
                "kind": "final",
                "final_answer": "duplicate iteration",
            }
        )


def test_react_observation_must_match_a_recorded_tool_decision() -> None:
    state = AgentState(user_input="complex task").start_react()
    state.record_react_decision(
        {
            "iteration": 1,
            "kind": "tool",
            "tool_name": "search_knowledge",
        }
    )

    with pytest.raises(ValueError, match="must match a recorded tool decision"):
        state.record_react_observation(
            {
                "iteration": 1,
                "tool_name": "save_research_note",
                "success": True,
                "summary": "must not be accepted",
            }
        )


def test_stage_one_declares_react_events_without_emitting_them_implicitly() -> None:
    assert AgentEventType.REACT_STARTED.value == "react_started"
    assert AgentEventType.DECISION_READY.value == "decision_ready"
    assert AgentEventType.OBSERVATION_READY.value == "observation_ready"
    assert AgentEventType.REACT_LIMIT_REACHED.value == "react_limit_reached"


def test_execution_policy_bounds_future_react_loop_and_observations() -> None:
    policy = AgentExecutionPolicy()

    assert policy.max_react_iterations == 6
    assert policy.max_knowledge_searches == 3
    assert policy.react_decision_timeout_seconds == 12.0
    assert policy.max_observation_chars == 3000

    control = AgentRunControl(
        policy=AgentExecutionPolicy(
            total_timeout_seconds=5.0,
            react_decision_timeout_seconds=2.0,
        )
    )
    assert 0 < control.bounded_react_decision_timeout() <= 2.0

    with pytest.raises(ValueError, match="max_react_iterations must be positive"):
        AgentExecutionPolicy(max_react_iterations=0)
    with pytest.raises(ValueError, match="max_knowledge_searches must be positive"):
        AgentExecutionPolicy(max_knowledge_searches=0)
    with pytest.raises(ValueError, match="react_decision_timeout_seconds must be positive"):
        AgentExecutionPolicy(react_decision_timeout_seconds=0)
    with pytest.raises(ValueError, match="max_observation_chars must be positive"):
        AgentExecutionPolicy(max_observation_chars=0)
