from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentRuntimeError
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentRunControl, run_react_decision_with_timeout
from backend.agent_core.state import AgentState
from backend.models.agent_react import (
    AgentEvidenceGateAssessment,
    AgentObservation,
    AgentRetrievalObservation,
    AgentReActDecision,
)
from backend.models.agent_runtime import AgentEvidenceItem, AgentPlanStep, AgentRouteDecision
from backend.services.agent_evidence_gate_service import AgentEvidenceGateService
from backend.services.agent_react_decision_service import AgentReActDecisionService


GraphEventSink = Callable[[AgentEventType, dict[str, Any]], None]
_KNOWLEDGE_SEARCH_TOOL = "search_knowledge_base"


class ReadingAgentGraphState(TypedDict, total=False):
    """Serializable public state for production and LangSmith Studio."""

    agent_state: dict[str, Any]
    conversation_run: dict[str, Any]
    route: dict[str, Any]
    route_metadata: dict[str, Any]
    emitted_event_types: list[str]


class ReadingAgentRuntimeContext(TypedDict, total=False):
    """Per-invocation objects that must never become Studio/checkpoint state."""

    event_sink: GraphEventSink | None
    control: AgentRunControl


def _coerce_agent_state(value: AgentState | dict[str, Any]) -> AgentState:
    if isinstance(value, AgentState):
        return value
    return AgentState.model_validate(value)


def _dump_agent_state(state: AgentState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _dump_conversation_run(run: Any) -> dict[str, Any]:
    if run is None:
        return {}
    history = getattr(run, "history", ()) or ()
    return {
        "conversation_id": str(getattr(run, "conversation_id", "") or ""),
        "user_message_id": str(getattr(run, "user_message_id", "") or ""),
        "assistant_message_id": str(getattr(run, "assistant_message_id", "") or ""),
        "history": [
            [str(item[0]), str(item[1])]
            for item in history
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ],
        "owner_id": str(getattr(run, "owner_id", "") or ""),
        "request_id": max(0, int(getattr(run, "request_id", 0) or 0)),
    }


def _load_conversation_run(payload: dict[str, Any] | None) -> Any:
    if not payload:
        return None
    history = tuple(
        (str(item[0]), str(item[1]))
        for item in payload.get("history", ())
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    return SimpleNamespace(
        conversation_id=str(payload.get("conversation_id", "") or ""),
        user_message_id=str(payload.get("user_message_id", "") or ""),
        assistant_message_id=str(payload.get("assistant_message_id", "") or ""),
        history=history,
        owner_id=str(payload.get("owner_id", "") or ""),
        request_id=max(0, int(payload.get("request_id", 0) or 0)),
    )


def _merge_emitted(existing: object, new_items: set[AgentEventType]) -> list[str]:
    values: set[str] = set()
    if isinstance(existing, (list, tuple, set, frozenset)):
        values.update(str(item) for item in existing if str(item))
    values.update(item.value for item in new_items)
    return sorted(values)


def _run_local_fingerprint(state: AgentState, payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    material = f"{state.run_id}\0{canonical}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def _react_action_fingerprint(state: AgentState, decision: AgentReActDecision) -> str:
    """Create a run-local opaque fingerprint for duplicate-action detection."""

    if decision.kind != "tool":
        return ""
    return _run_local_fingerprint(
        state,
        {
            "tool_name": decision.tool_name,
            "arguments": decision.arguments,
        },
    )


def _is_repeated_react_action(
    state: AgentState,
    decision: AgentReActDecision,
) -> bool:
    if decision.kind != "tool":
        return False
    return any(
        previous.kind == "tool"
        and previous.tool_name == decision.tool_name
        and previous.arguments == decision.arguments
        for previous in state.react.decisions[:-1]
    )


def _knowledge_search_count(state: AgentState) -> int:
    return sum(
        str(item.get("name", "") or item.get("tool_name", "") or "")
        == _KNOWLEDGE_SEARCH_TOOL
        for item in state.tool_calls
        if isinstance(item, dict)
    )


def _prior_evidence_ids(state: AgentState) -> set[str]:
    return {
        evidence_id
        for observation in state.react.observations
        for evidence_id in observation.evidence_ids
        if evidence_id
    }


def _cumulative_knowledge_evidence(state: AgentState) -> list[AgentEvidenceItem]:
    evidence: list[AgentEvidenceItem] = []
    seen: set[str] = set()
    for result in state.tool_results:
        if not isinstance(result, dict):
            continue
        tool_name = str(result.get("tool_name", "") or result.get("name", "") or "")
        if tool_name != _KNOWLEDGE_SEARCH_TOOL:
            continue
        data = result.get("data", {})
        if not isinstance(data, dict):
            continue
        raw_evidence = data.get("evidence", ())
        if not isinstance(raw_evidence, (list, tuple)):
            continue
        for raw in raw_evidence:
            try:
                item = (
                    raw
                    if isinstance(raw, AgentEvidenceItem)
                    else AgentEvidenceItem.model_validate(raw)
                )
            except Exception:
                continue
            if item.evidence_id and item.evidence_id not in seen:
                evidence.append(item)
                seen.add(item.evidence_id)
    return evidence


def _latest_evidence_gate(state: AgentState) -> AgentEvidenceGateAssessment | None:
    for observation in reversed(state.react.observations):
        if observation.retrieval is not None and observation.retrieval.gate is not None:
            return observation.retrieval.gate
    return None


def _retrieval_observation(
    state: AgentState,
    decision: AgentReActDecision,
    result: dict[str, Any],
) -> AgentRetrievalObservation | None:
    if decision.tool_name != _KNOWLEDGE_SEARCH_TOOL:
        return None
    data = dict(result.get("data", {}) or {})
    evidence_ids = [item.evidence_id for item in state.evidence]
    previous = _prior_evidence_ids(state)
    results = data.get("results", ())
    result_count = len(results) if isinstance(results, (list, tuple)) else 0
    query = str(
        data.get("query", "")
        or decision.arguments.get("query", "")
        or ""
    ).strip()
    return AgentRetrievalObservation(
        query=query,
        retrieval_strategy=str(data.get("retrieval_strategy", "") or ""),
        result_count=result_count,
        evidence_count=len(evidence_ids),
        citation_count=len(state.citations),
        novel_evidence_count=sum(item not in previous for item in evidence_ids),
        fallback_reason=str(data.get("fallback_reason", "") or ""),
    )


class ReadingAgentGraph:
    """Bounded LangGraph workflow for the AITrans Reading Agent.

    Deterministic and single-tool requests stay on the established direct path.
    Only ``complex`` routes enter a bounded ReAct loop where the model chooses
    one registered Tool or Final per iteration and every Tool result is converted
    into a compact observation before the next decision. Knowledge retrieval is
    agentic only at the query/continue/stop layer; dense/sparse retrieval,
    fusion, reranking, evidence construction, and citations remain owned by the
    RAG subsystem. A deterministic evidence-sufficiency gate evaluates cumulative
    retrieval evidence and can stop further retrieval before another LLM decision
    is spent. Tool execution, safe retries, grounding, and write confirmation
    remain owned by the existing ProductAgentService boundary.
    """

    node_names = (
        "prepare_conversation",
        "route_request",
        "execute_direct",
        "start_react",
        "decide_react",
        "execute_react_tool",
        "finalize_react",
        "finalize_conversation",
    )

    def __init__(
        self,
        adapter: ProductAgentRuntimeAdapter,
        react_decision_service: AgentReActDecisionService | Any | None = None,
        evidence_gate_service: AgentEvidenceGateService | Any | None = None,
    ) -> None:
        self._adapter = adapter
        self._react_decision_service = react_decision_service or AgentReActDecisionService()
        self._evidence_gate_service = evidence_gate_service or AgentEvidenceGateService()
        builder = StateGraph(
            ReadingAgentGraphState,
            context_schema=ReadingAgentRuntimeContext,
        )
        builder.add_node("prepare_conversation", self._prepare_conversation)
        builder.add_node("route_request", self._route_request)
        builder.add_node("execute_direct", self._execute_direct)
        builder.add_node("start_react", self._start_react)
        builder.add_node("decide_react", self._decide_react)
        builder.add_node("execute_react_tool", self._execute_react_tool)
        builder.add_node("finalize_react", self._finalize_react)
        builder.add_node("finalize_conversation", self._finalize_conversation)

        builder.add_edge(START, "prepare_conversation")
        builder.add_edge("prepare_conversation", "route_request")
        builder.add_conditional_edges(
            "route_request",
            self._route_branch,
            {"complex": "start_react", "direct": "execute_direct"},
        )
        builder.add_edge("execute_direct", "finalize_conversation")
        builder.add_edge("start_react", "decide_react")
        builder.add_conditional_edges(
            "decide_react",
            self._decision_branch,
            {
                "tool": "execute_react_tool",
                "final": "finalize_react",
                "limit": "finalize_react",
            },
        )
        builder.add_conditional_edges(
            "execute_react_tool",
            self._observation_branch,
            {
                "continue": "decide_react",
                "finalize": "finalize_react",
                "confirmation": "finalize_conversation",
            },
        )
        builder.add_edge("finalize_react", "finalize_conversation")
        builder.add_edge("finalize_conversation", END)
        self._compiled = builder.compile()

    @property
    def compiled_graph(self):
        return self._compiled

    @staticmethod
    def _runtime(
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> tuple[GraphEventSink | None, AgentRunControl]:
        context = runtime.context or {}
        return context.get("event_sink"), context.get("control") or AgentRunControl()

    def _abort(self, graph_state: ReadingAgentGraphState, exc: Exception) -> None:
        self._adapter.abort_conversation(
            _load_conversation_run(graph_state.get("conversation_run")),
            exc,
        )

    def _registered_tools(self) -> tuple[Any, ...]:
        service = getattr(self._adapter, "_service", None)
        list_tools = getattr(service, "list_tools", None)
        if callable(list_tools):
            return tuple(list_tools())
        registry = getattr(service, "_registry", None)
        list_tools = getattr(registry, "list_tools", None)
        if callable(list_tools):
            return tuple(list_tools())
        return ()

    def _emit_react_limit(
        self,
        state: AgentState,
        emit: GraphEventSink | None,
        *,
        reason: str,
    ) -> set[AgentEventType]:
        state.mark_react_status("limit_reached")
        if emit is None:
            return set()
        emit(
            AgentEventType.REACT_LIMIT_REACHED,
            {
                "iteration": state.react.iteration,
                "tool_call_count": len(state.tool_calls),
                "knowledge_search_count": _knowledge_search_count(state),
                "reason": reason,
            },
        )
        return {AgentEventType.REACT_LIMIT_REACHED}

    def _prepare_conversation(self, graph_state: ReadingAgentGraphState) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        conversation_run = self._adapter.begin_conversation(state)
        return {
            "agent_state": _dump_agent_state(state),
            "conversation_run": _dump_conversation_run(conversation_run),
        }

    def _route_request(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        _, control = self._runtime(runtime)
        try:
            route, metadata = self._adapter.resolve_route(state, control=control)
        except Exception as exc:
            self._abort(graph_state, exc)
            raise
        return {
            "agent_state": _dump_agent_state(state),
            "route": route.model_dump(mode="json"),
            "route_metadata": dict(metadata),
        }

    @staticmethod
    def _route_branch(graph_state: ReadingAgentGraphState) -> str:
        route = AgentRouteDecision.model_validate(graph_state.get("route", {}))
        return "complex" if route.kind == "complex" else "direct"

    def _execute_direct(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        route = AgentRouteDecision.model_validate(graph_state.get("route", {}))
        emit, control = self._runtime(runtime)
        try:
            state, emitted = self._adapter.execute_product(
                state,
                emit,
                control=control,
                resolved_route=route,
                route_metadata=dict(graph_state.get("route_metadata", {}) or {}),
            )
        except Exception as exc:
            self._abort(graph_state, exc)
            raise
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _start_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        state.start_react()
        emitted: set[AgentEventType] = set()
        if emit is not None:
            route_metadata = dict(graph_state.get("route_metadata", {}) or {})
            emit(
                AgentEventType.PLAN_READY,
                {
                    "mode": "react",
                    "route_kind": state.route.kind,
                    "route_source": state.route.source,
                    "request_id": state.execution.request_id,
                    **route_metadata,
                },
            )
            emit(
                AgentEventType.REACT_STARTED,
                {
                    "max_iterations": control.policy.max_react_iterations,
                    "max_tool_calls": control.policy.max_tool_calls,
                    "max_knowledge_searches": control.policy.max_knowledge_searches,
                    "request_id": state.execution.request_id,
                },
            )
            emitted.update({AgentEventType.PLAN_READY, AgentEventType.REACT_STARTED})
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _decide_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        if state.react.iteration >= control.policy.max_react_iterations:
            emitted = self._emit_react_limit(
                state, emit, reason="iteration_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        latest_gate = _latest_evidence_gate(state)
        if latest_gate is not None and latest_gate.action == "stop":
            decision = AgentReActDecision(
                iteration=state.react.iteration + 1,
                kind="final",
                action_summary="Use the accumulated evidence after the retrieval quality gate stopped further search.",
            )
            state.record_react_decision(decision)
            emitted: set[AgentEventType] = set()
            if emit is not None:
                emit(
                    AgentEventType.DECISION_READY,
                    {
                        "iteration": decision.iteration,
                        "kind": decision.kind,
                        "tool_name": "",
                        "argument_keys": [],
                        "action_fingerprint": "",
                        "provider": "deterministic-evidence-gate",
                        "model": "",
                        "prompt_id": "evidence-gate",
                    },
                )
                emitted.add(AgentEventType.DECISION_READY)
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        tools = self._registered_tools()
        if not tools:
            exc = AgentRuntimeError(
                "Complex ReAct route has no registered tools.",
                stage="react_decision",
                fallback_reason="missing_tool_registry",
            )
            self._abort(graph_state, exc)
            raise exc

        iteration = state.react.iteration + 1
        knowledge_search_count = _knowledge_search_count(state)
        payload = self._adapter.build_payload(state)
        try:
            decision = run_react_decision_with_timeout(
                lambda: self._react_decision_service.decide(
                    iteration=iteration,
                    tools=tools,
                    observations=tuple(state.react.observations),
                    max_observation_chars=control.policy.max_observation_chars,
                    remaining_tool_calls=max(
                        0, control.policy.max_tool_calls - len(state.tool_calls)
                    ),
                    remaining_knowledge_searches=max(
                        0,
                        min(
                            control.policy.max_knowledge_searches,
                            control.policy.max_tool_calls,
                        )
                        - knowledge_search_count,
                    ),
                    **payload,
                ),
                control=control,
            )
            state.record_react_decision(decision)
        except Exception as exc:
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        emitted: set[AgentEventType] = set()
        action_fingerprint = _react_action_fingerprint(state, decision)
        if emit is not None:
            emit(
                AgentEventType.DECISION_READY,
                {
                    "iteration": decision.iteration,
                    "kind": decision.kind,
                    "tool_name": decision.tool_name,
                    "argument_keys": sorted(decision.arguments),
                    "action_fingerprint": action_fingerprint,
                    "action_summary": decision.action_summary,
                    "provider": str(
                        getattr(self._react_decision_service, "provider_name", "") or ""
                    ),
                    "model": str(
                        getattr(self._react_decision_service, "model", "") or ""
                    ),
                    "prompt_id": str(
                        getattr(self._react_decision_service, "prompt_id", "") or ""
                    ),
                },
            )
            emitted.add(AgentEventType.DECISION_READY)

        if _is_repeated_react_action(state, decision):
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="repeated_action_detected"
                )
            )
        elif (
            decision.kind == "tool"
            and decision.tool_name == _KNOWLEDGE_SEARCH_TOOL
            and knowledge_search_count
            >= min(control.policy.max_knowledge_searches, control.policy.max_tool_calls)
        ):
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="knowledge_search_budget_exhausted"
                )
            )

        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    @staticmethod
    def _decision_branch(graph_state: ReadingAgentGraphState) -> str:
        state = _coerce_agent_state(graph_state["agent_state"])
        if state.react.status == "limit_reached":
            return "limit"
        decision = state.react.last_decision
        if decision is None:
            raise AgentRuntimeError(
                "ReAct decision node completed without a decision.",
                stage="react_decision",
                fallback_reason="missing_react_decision",
            )
        return "tool" if decision.kind == "tool" else "final"

    def _execute_react_tool(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        decision = state.react.last_decision
        if decision is None or decision.kind != "tool":
            exc = AgentRuntimeError(
                "ReAct action node requires a tool decision.",
                stage="react_action",
                fallback_reason="invalid_react_action",
            )
            self._abort(graph_state, exc)
            raise exc

        if len(state.tool_calls) >= control.policy.max_tool_calls:
            emitted = self._emit_react_limit(
                state, emit, reason="tool_call_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }
        if (
            decision.tool_name == _KNOWLEDGE_SEARCH_TOOL
            and _knowledge_search_count(state)
            >= min(control.policy.max_knowledge_searches, control.policy.max_tool_calls)
        ):
            emitted = self._emit_react_limit(
                state, emit, reason="knowledge_search_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        step = AgentPlanStep(
            step_id=f"react-{decision.iteration}",
            tool_name=decision.tool_name,
            arguments=dict(decision.arguments),
        )
        try:
            state, emitted = self._adapter.execute_plan_step(
                state,
                step,
                emit,
                control=control,
            )
        except Exception as exc:
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        if state.response_state.status == "confirmation_required":
            state.mark_react_status("confirmation_required")
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        result = state.tool_results[-1] if state.tool_results else {}
        summary = str(result.get("output_text", "") or "").strip()
        if not summary:
            summary = f"{decision.tool_name} completed."
        summary = summary[: control.policy.max_observation_chars]
        retrieval = _retrieval_observation(state, decision, result)

        if retrieval is not None:
            search_count = _knowledge_search_count(state)
            max_searches = min(
                control.policy.max_knowledge_searches,
                control.policy.max_tool_calls,
            )
            gate = self._evidence_gate_service.assess(
                evidence=_cumulative_knowledge_evidence(state),
                latest_retrieval=retrieval,
                search_count=search_count,
                remaining_searches=max(0, max_searches - search_count),
            )
            retrieval = retrieval.model_copy(update={"gate": gate})
            if emit is not None:
                emit(
                    AgentEventType.EVIDENCE_GATE_EVALUATED,
                    {
                        "iteration": decision.iteration,
                        "action": gate.action,
                        "coverage_score": gate.coverage_score,
                        "diversity_score": gate.diversity_score,
                        "novelty_score": gate.novelty_score,
                        "quality_score": gate.quality_score,
                        "evidence_count": gate.evidence_count,
                        "unique_source_count": gate.unique_source_count,
                        "unique_location_count": gate.unique_location_count,
                        "novel_evidence_count": gate.novel_evidence_count,
                        "search_count": gate.search_count,
                        "remaining_searches": gate.remaining_searches,
                        "retrieval_fallback": gate.retrieval_fallback,
                        "reason_codes": list(gate.reason_codes),
                    },
                )
                emitted.add(AgentEventType.EVIDENCE_GATE_EVALUATED)

        observation = AgentObservation(
            iteration=decision.iteration,
            tool_name=decision.tool_name,
            success=True,
            summary=summary,
            evidence_ids=[item.evidence_id for item in state.evidence],
            citation_ids=[item.citation_id for item in state.citations],
            retrieval=retrieval,
        )
        state.record_react_observation(observation)

        if emit is not None:
            observation_payload: dict[str, Any] = {
                "observation_id": observation.observation_id,
                "iteration": observation.iteration,
                "tool_name": observation.tool_name,
                "success": observation.success,
                "summary_chars": len(observation.summary),
                "evidence_count": len(observation.evidence_ids),
                "citation_count": len(observation.citation_ids),
            }
            if retrieval is not None:
                observation_payload.update(
                    {
                        "knowledge_search_count": _knowledge_search_count(state),
                        "query_fingerprint": _run_local_fingerprint(
                            state, {"query": retrieval.query}
                        ),
                        "retrieval_strategy": retrieval.retrieval_strategy,
                        "result_count": retrieval.result_count,
                        "novel_evidence_count": retrieval.novel_evidence_count,
                        "retrieval_fallback": bool(retrieval.fallback_reason),
                        "gate_action": (
                            retrieval.gate.action if retrieval.gate is not None else ""
                        ),
                        "gate_quality_score": (
                            retrieval.gate.quality_score
                            if retrieval.gate is not None
                            else 0.0
                        ),
                    }
                )
            emit(AgentEventType.OBSERVATION_READY, observation_payload)
            emitted.add(AgentEventType.OBSERVATION_READY)

        if len(state.tool_calls) >= control.policy.max_tool_calls:
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="tool_call_budget_exhausted"
                )
            )
        elif state.react.iteration >= control.policy.max_react_iterations:
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="iteration_budget_exhausted"
                )
            )

        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    @staticmethod
    def _observation_branch(graph_state: ReadingAgentGraphState) -> str:
        state = _coerce_agent_state(graph_state["agent_state"])
        if state.response_state.status == "confirmation_required":
            return "confirmation"
        if state.react.status == "limit_reached":
            return "finalize"
        gate = _latest_evidence_gate(state)
        if gate is not None and gate.action == "stop":
            return "finalize"
        return "continue"

    def _finalize_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        emitted: set[AgentEventType] = set()

        try:
            if state.tool_results:
                state, emitted = self._adapter.synthesize_multi_step(
                    state,
                    emit,
                    control=control,
                )
            else:
                decision: AgentReActDecision | None = state.react.last_decision
                if decision is None or decision.kind != "final" or not decision.final_answer:
                    raise AgentRuntimeError(
                        "ReAct reached its execution limit before producing an answer or observation.",
                        stage="react_finalize",
                        fallback_reason="react_limit_without_observation",
                    )
                state.ui_mode = "assistant"
                state.apply_response(
                    {
                        "status": "completed",
                        "output_text": decision.final_answer,
                        "provider": str(
                            getattr(self._react_decision_service, "provider_name", "") or ""
                        ),
                        "model": str(
                            getattr(self._react_decision_service, "model", "") or ""
                        ),
                        "request_id": state.execution.request_id,
                    }
                )
                if emit is not None:
                    emit(
                        AgentEventType.SYNTHESIS_READY,
                        {
                            "source": "react_decision",
                            "provider": state.response_state.provider,
                            "model": state.response_state.model,
                            "request_id": state.execution.request_id,
                            "prompt_id": str(
                                getattr(self._react_decision_service, "prompt_id", "") or ""
                            ),
                            "grounded": False,
                        },
                    )
                    emitted.add(AgentEventType.SYNTHESIS_READY)
        except Exception as exc:
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        if state.react.status != "limit_reached":
            state.mark_react_status("completed")
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _finalize_conversation(
        self,
        graph_state: ReadingAgentGraphState,
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        self._adapter.complete_conversation(
            _load_conversation_run(graph_state.get("conversation_run")), state
        )
        return {"agent_state": _dump_agent_state(state)}

    def _invoke(
        self,
        state: AgentState,
        *,
        emit: GraphEventSink | None,
        control: AgentRunControl | None,
    ) -> tuple[AgentState, set[AgentEventType]]:
        initial: ReadingAgentGraphState = {
            "agent_state": _dump_agent_state(state),
            "conversation_run": {},
            "route": {},
            "route_metadata": {},
            "emitted_event_types": [],
        }
        result = self._compiled.invoke(
            initial,
            context={
                "event_sink": emit,
                "control": control or AgentRunControl(),
            },
        )
        final_state = _coerce_agent_state(
            result.get("agent_state", initial["agent_state"])
        )
        emitted = {
            AgentEventType(item) for item in result.get("emitted_event_types", ())
        }
        return final_state, emitted

    def __call__(self, state: AgentState) -> AgentState:
        final_state, _ = self._invoke(state, emit=None, control=None)
        return final_state

    def run_with_events(
        self,
        state: AgentState,
        emit: GraphEventSink,
        *,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        final_state, emitted = self._invoke(state, emit=emit, control=control)
        self._adapter.emit_compatibility_events(final_state, emitted, emit)
        return final_state

    def close(self) -> None:
        self._adapter.close()
        close = getattr(self._react_decision_service, "close", None)
        if callable(close):
            close()


__all__ = [
    "ReadingAgentGraph",
    "ReadingAgentGraphState",
    "ReadingAgentRuntimeContext",
]
