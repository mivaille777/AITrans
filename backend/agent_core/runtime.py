from __future__ import annotations

from typing import Any, Callable

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.exceptions import AgentBudgetExceededError, AgentCancelledError
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import AgentState

AgentEventSink = Callable[[AgentEvent], None]
AgentRunRecorder = Callable[[AgentState, tuple[AgentEvent, ...]], None]


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, AgentBudgetExceededError):
        return "execution_budget_exhausted"
    if isinstance(exc, AgentCancelledError):
        return "user_cancelled"
    return str(getattr(exc, "fallback_reason", "") or "no_safe_fallback")


class AgentRuntime:
    """State-oriented orchestration layer around existing agent services.

    Agent Core owns correlation IDs, total execution budget, cooperative
    cancellation and normalized lifecycle events. Existing product services keep
    ownership of planning, tool validation, confirmation gates and synthesis.
    Runtime telemetry persistence is a best-effort observer and cannot change
    execution outcomes.

    Stage 5.8 adds an optional ``collaboration_adapter`` that runs inside this
    same reliability boundary after reading-context resolution and before the
    canonical workflow adapter. It may enrich ``AgentState`` with advisory
    multi-agent context, but it does not replace the production workflow or its
    safety/grounding contracts.
    """

    def __init__(
        self,
        *,
        context_provider: Callable[[AgentState], dict[str, Any]] | None = None,
        planner: Callable[[AgentState], dict[str, Any]] | None = None,
        tool_executor: Callable[[AgentState], dict[str, Any]] | None = None,
        collaboration_adapter: Any | None = None,
        workflow_adapter: Callable[[AgentState], AgentState] | None = None,
        run_recorder: AgentRunRecorder | None = None,
    ) -> None:
        self.context_provider = context_provider
        self.planner = planner
        self.tool_executor = tool_executor
        self.collaboration_adapter = collaboration_adapter
        self.workflow_adapter = workflow_adapter
        self.run_recorder = run_recorder
        self.events: list[AgentEvent] = []
        self._event_sink: AgentEventSink | None = None
        self._active_state: AgentState | None = None
        self._control: AgentRunControl | None = None

    def _emit(self, event_type: AgentEventType, payload: dict[str, Any]) -> None:
        state = self._active_state
        control = self._control
        event = AgentEvent(
            event_type=event_type,
            payload=payload,
            run_id=state.run_id if state is not None else "",
            trace_id=state.trace_id if state is not None else "",
            elapsed_ms=control.elapsed_ms if control is not None else 0,
        )
        self.events.append(event)
        if self._event_sink is not None:
            try:
                self._event_sink(event)
            except Exception:
                # Observability/transport is deliberately best-effort. A closed
                # WebSocket or broken debug sink must not change Agent behavior.
                pass

    def _run_collaboration(self, state: AgentState, control: AgentRunControl) -> AgentState:
        adapter = self.collaboration_adapter
        if adapter is None:
            return state

        should_run = getattr(adapter, "should_run", None)
        if callable(should_run) and not bool(should_run(state)):
            return state

        eventful_run = getattr(adapter, "run_with_events", None)
        if callable(eventful_run):
            state = eventful_run(state, self._emit, control=control)
        elif callable(adapter):
            state = adapter(state)
        state.sync_contract()
        return state

    def execute(
        self,
        state: AgentState,
        *,
        event_sink: AgentEventSink | None = None,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        previous_sink = self._event_sink
        previous_state = self._active_state
        previous_control = self._control
        self._event_sink = event_sink
        self._active_state = state
        self._control = control or AgentRunControl()
        self.events.clear()
        state.sync_contract()

        try:
            active_control = self._control
            active_control.checkpoint("agent_start")
            self._emit(
                AgentEventType.AGENT_START,
                {
                    "session_id": state.session_id,
                    "run_id": state.run_id,
                    "trace_id": state.trace_id,
                    "budget_ms": int(active_control.policy.total_timeout_seconds * 1000),
                },
            )

            active_control.checkpoint("context_resolution")
            if self.context_provider:
                state.apply_reading_context(self.context_provider(state))
            else:
                state.sync_contract()
            active_control.checkpoint("context_ready")
            self._emit(AgentEventType.CONTEXT_READY, state.browser_context)

            state = self._run_collaboration(state, active_control)

            if self.workflow_adapter is not None:
                previous_call_count = len(state.tool_calls)
                previous_result_count = len(state.tool_results)
                eventful_run = getattr(self.workflow_adapter, "run_with_events", None)
                if callable(eventful_run):
                    state = eventful_run(state, self._emit, control=active_control)
                else:
                    active_control.checkpoint("workflow")
                    state = self.workflow_adapter(state)
                    active_control.checkpoint("workflow_result")
                    for call in state.tool_calls[previous_call_count:]:
                        self._emit(AgentEventType.TOOL_CALL, call)
                    for result in state.tool_results[previous_result_count:]:
                        self._emit(AgentEventType.TOOL_RESULT, result)

                state.sync_contract()
                # Do not re-check cancellation after a workflow has returned a
                # completed result. A confirmed write may have finished while a
                # late cancel request was arriving; reporting the real side
                # effect is safer than claiming it was cancelled.
                self._emit(
                    AgentEventType.AGENT_END,
                    {
                        "intent": state.intent,
                        "status": state.response.get("status", ""),
                        "ui_mode": state.ui_mode,
                        "total_duration_ms": active_control.elapsed_ms,
                    },
                )
                return state

            if self.planner:
                active_control.checkpoint("planner")
                state.planned_action = self.planner(state)
                active_control.checkpoint("planner_result")
                state.intent = state.planned_action.get("intent", state.intent)
                state.sync_contract()
                self._emit(AgentEventType.PLAN_READY, state.planned_action)

            if self.tool_executor:
                active_control.checkpoint("tool")
                self._emit(
                    AgentEventType.TOOL_CALL,
                    {
                        "name": state.planned_action.get("tool_name", ""),
                        "arguments": state.planned_action.get("arguments", {}),
                    },
                )
                result = self.tool_executor(state)
                active_control.checkpoint("tool_result")
                state.tool_results.append(result)
                state.sync_contract()
                self._emit(AgentEventType.TOOL_RESULT, result)

            state.sync_contract()
            self._emit(
                AgentEventType.AGENT_END,
                {"intent": state.intent, "total_duration_ms": active_control.elapsed_ms},
            )
            return state
        except AgentCancelledError as exc:
            state.sync_contract()
            self._emit(
                AgentEventType.CANCELLED,
                {
                    "code": "cancelled",
                    "message": str(exc),
                    "fallback_reason": "user_cancelled",
                },
            )
            self._emit(
                AgentEventType.AGENT_END,
                {
                    "intent": state.intent,
                    "status": "cancelled",
                    "ui_mode": state.ui_mode,
                    "total_duration_ms": self._control.elapsed_ms if self._control else 0,
                },
            )
            raise
        except Exception as exc:
            state.sync_contract()
            self._emit(
                AgentEventType.FAILURE,
                {
                    "code": type(exc).__name__,
                    "message": str(exc) or "Agent execution failed.",
                    "stage": str(getattr(exc, "stage", "runtime") or "runtime"),
                    "fallback_reason": _fallback_reason(exc),
                },
            )
            self._emit(
                AgentEventType.AGENT_END,
                {
                    "intent": state.intent,
                    "status": "failed",
                    "ui_mode": state.ui_mode,
                    "total_duration_ms": self._control.elapsed_ms if self._control else 0,
                },
            )
            raise
        finally:
            if self.run_recorder is not None:
                try:
                    self.run_recorder(state, tuple(self.events))
                except Exception:
                    # Persistence is diagnostic only. Disk/SQLite failures must
                    # not change Agent success, failure, cancellation or safety.
                    pass
            self._event_sink = previous_sink
            self._active_state = previous_state
            self._control = previous_control
