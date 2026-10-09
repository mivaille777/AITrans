from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.ai.knowledge_context import knowledge_context_diagnostics
from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentPauseRequestedError,
    AgentRuntimeError,
)
from backend.agent_core.orchestration.agent_registry import build_default_agent_registry
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.state import AgentState

AgentEventSink = Callable[[AgentEvent], None]
AgentRunRecorder = Callable[[AgentState, tuple[AgentEvent, ...]], None]
AgentEventRecorder = Callable[[AgentState, AgentEvent, int], int | None]


def _optional_event_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


@lru_cache(maxsize=32)
def _registered_agent_version(agent_id: str) -> str | None:
    try:
        return build_default_agent_registry().get(agent_id).version
    except KeyError:
        return None


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
        event_recorder: AgentEventRecorder | None = None,
    ) -> None:
        if getattr(workflow_adapter, "graph_role", "") == "canonical_root" and (
            planner is not None or tool_executor is not None
        ):
            raise ValueError(
                "The canonical Root Graph owns planning and tool dispatch; "
                "legacy runtime handlers cannot run alongside it."
            )
        self.context_provider = context_provider
        self.planner = planner
        self.tool_executor = tool_executor
        self.collaboration_adapter = collaboration_adapter
        self.workflow_adapter = workflow_adapter
        self._selected_graph_version = ""
        self.run_recorder = run_recorder
        self.event_recorder = event_recorder
        self.events: list[AgentEvent] = []
        self._event_sink: AgentEventSink | None = None
        self._active_state: AgentState | None = None
        self._control: AgentRunControl | None = None
        configure_preworkflow = getattr(workflow_adapter, "configure_preworkflow", None)
        if callable(configure_preworkflow):
            configure_preworkflow(
                context_provider=context_provider,
                collaboration_adapter=collaboration_adapter,
            )

    def _emit(self, event_type: AgentEventType, payload: dict[str, Any]) -> None:
        state = self._active_state
        control = self._control
        agent_id = _optional_event_text(payload.get("agent_id"))
        event = AgentEvent(
            event_type=event_type,
            payload=payload,
            task_id=state.task_id if state is not None else "",
            agent_id=agent_id,
            agent_version=(
                _optional_event_text(payload.get("agent_version"))
                or (_registered_agent_version(agent_id) if agent_id else None)
            ),
            node_name=_optional_event_text(payload.get("node_name")),
            subgraph_path=_optional_event_text(payload.get("subgraph_path")),
            run_id=state.run_id if state is not None else "",
            trace_id=state.trace_id if state is not None else "",
            step_id=str(payload.get("step_id", "") or ""),
            tool_call_id=str(payload.get("tool_call_id", "") or ""),
            elapsed_ms=control.elapsed_ms if control is not None else 0,
        )
        self.events.append(event)
        event.sequence = len(self.events) - 1
        temporary = bool(
            state is not None and state.browser_context.get("temporary", False)
        )
        if self.event_recorder is not None and state is not None and not temporary:
            try:
                persisted_sequence = self.event_recorder(
                    state, event, len(self.events) - 1
                )
                if persisted_sequence is not None:
                    event.sequence = max(0, int(persisted_sequence))
            except Exception:  # noqa: BLE001,S110 - observer is best effort
                # Live trace durability is observational and cannot fail the run.
                pass
        if self._event_sink is not None:
            try:
                self._event_sink(event)
            except Exception:  # noqa: BLE001,S110 - transport is best effort
                # Observability/transport is deliberately best-effort. A closed
                # WebSocket or broken debug sink must not change Agent behavior.
                pass

    def _run_collaboration(
        self, state: AgentState, control: AgentRunControl
    ) -> AgentState:
        adapter = self.collaboration_adapter
        if adapter is None:
            return state

        prepare_state = getattr(adapter, "prepare_state", None)
        if callable(prepare_state):
            state = prepare_state(state)

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

    def select_graph_version(
        self,
        graph_version: str,
        *,
        state_schema_version: int | None = None,
        engine: str | None = None,
    ) -> None:
        """Pin the workflow builder before a durable run resumes."""

        selector = getattr(self.workflow_adapter, "select_graph_version", None)
        if callable(selector):
            parameters = inspect.signature(selector).parameters
            options: dict[str, Any] = {
                "state_schema_version": state_schema_version
            }
            if "pin" in parameters:
                options["pin"] = True
            if "engine" in parameters and engine is not None:
                options["engine"] = engine
            selector(graph_version, **options)
        self._selected_graph_version = str(graph_version or "").strip()

    def restore_checkpoint(self, run_id: str) -> AgentState:
        """Return the latest persisted graph state for an explicit resume."""

        if not self._selected_graph_version:
            prepare = getattr(
                self.workflow_adapter, "prepare_checkpoint_resume", None
            )
            if callable(prepare):
                prepare(run_id)
        loader = getattr(self.workflow_adapter, "checkpoint_state", None)
        state = loader(run_id) if callable(loader) else None
        if not isinstance(state, AgentState):
            raise AgentRuntimeError(
                f"No resumable Agent checkpoint exists for run {run_id!r}.",
                stage="checkpoint",
                fallback_reason="checkpoint_not_found",
            )
        context = dict(state.browser_context)
        context["confirmed_write_tools"] = []
        context.pop("write_confirmation_decision", None)
        context.pop("plan_confirmation_decision", None)
        context.pop("native_task_retry_resume", None)
        state.browser_context = context
        state.sync_contract()
        return state

    def checkpoint_metadata(self, run_id: str) -> dict[str, str | int] | None:
        loader = getattr(self.workflow_adapter, "checkpoint_metadata", None)
        return loader(run_id) if callable(loader) else None

    def checkpoint_orchestration_state(self, run_id: str) -> dict | None:
        loader = getattr(
            self.workflow_adapter, "checkpoint_orchestration_state", None
        )
        return loader(run_id) if callable(loader) else None

    def prepare_task_retry(self, state: AgentState, task_id: str) -> tuple[str, ...]:
        """Reopen one failed orchestration task through the configured workflow."""

        prepare = getattr(self.workflow_adapter, "prepare_task_retry", None)
        if not callable(prepare):
            raise AgentRuntimeError(
                "The configured Agent workflow does not support task retry.",
                stage="checkpoint",
                fallback_reason="task_retry_unavailable",
            )
        retried = tuple(prepare(state, task_id))
        context = dict(state.browser_context)
        # A confirmation authorizes one concrete write attempt only. A resumed
        # or retried task must request a fresh confirmation if it reaches a write.
        context["confirmed_write_tools"] = []
        context.pop("write_confirmation_decision", None)
        context["retry_task_id"] = str(task_id or "").strip()
        state.browser_context = context
        state.sync_contract()
        return retried

    def execute(
        self,
        state: AgentState,
        *,
        event_sink: AgentEventSink | None = None,
        control: AgentRunControl | None = None,
        resume: bool = False,
    ) -> AgentState:
        resume_context = {
            key: state.browser_context[key]
            for key in (
                "confirmed_write_tools",
                "enabled_tools",
                "write_confirmation_decision",
                "plan_confirmation_decision",
                "filesystem_access",
                "native_task_retry_resume",
                "retry_task_id",
            )
            if key in state.browser_context
        }
        resume = bool(resume or resume_context.get("native_task_retry_resume"))
        if resume:
            state = self.restore_checkpoint(state.run_id)
            if resume_context:
                state.browser_context = {
                    **state.browser_context,
                    **resume_context,
                }
                state.sync_contract()
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
                    "budget_ms": int(
                        active_control.policy.total_timeout_seconds * 1000
                    ),
                    "resumed": resume,
                },
            )

            if resume:
                resume_with_events = getattr(
                    self.workflow_adapter,
                    "resume_with_events",
                    None,
                )
                if not callable(resume_with_events):
                    raise AgentRuntimeError(
                        "The configured Agent workflow cannot resume checkpoints.",
                        stage="checkpoint",
                        fallback_reason="checkpoint_unavailable",
                    )
                state = resume_with_events(
                    state,
                    self._emit,
                    control=active_control,
                )
                state.sync_contract()
                self._active_state = state
                if state.browser_context.get("task_completion"):
                    self._emit(AgentEventType.TASK_VERIFICATION, state.browser_context["task_completion"])
                self._emit(
                    AgentEventType.AGENT_END,
                    {
                        "intent": state.intent,
                        "status": state.response.get("status", ""),
                        "ui_mode": state.ui_mode,
                        "total_duration_ms": active_control.elapsed_ms,
                        "resumed": True,
                    },
                )
                return state

            manages_preworkflow = bool(
                getattr(self.workflow_adapter, "manages_preworkflow", False)
            )
            if not manages_preworkflow:
                active_control.checkpoint("context_resolution")
                if self.context_provider:
                    state.apply_reading_context(self.context_provider(state))
                else:
                    state.sync_contract()
                active_control.checkpoint("context_ready")
                public_context = {
                    key: value
                    for key, value in state.browser_context.items()
                    if key != "knowledge_context"
                }
                self._emit(AgentEventType.CONTEXT_READY, public_context)
                knowledge_diagnostics = knowledge_context_diagnostics(
                    state.browser_context.get("knowledge_context")
                )
                if knowledge_diagnostics:
                    self._emit(
                        AgentEventType.KNOWLEDGE_CONTEXT_READY,
                        knowledge_diagnostics,
                    )

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
                if state.browser_context.get("task_completion"):
                    self._emit(AgentEventType.TASK_VERIFICATION, state.browser_context["task_completion"])
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
                {
                    "intent": state.intent,
                    "total_duration_ms": active_control.elapsed_ms,
                },
            )
            return state
        except AgentPauseRequestedError:
            # The graph has not started the next node; its previous checkpoint
            # remains the exact point from which resume must continue.
            raise
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
            self._record_incomplete_acceptance(state, exc, cancelled=True)
            self._emit(
                AgentEventType.AGENT_END,
                {
                    "intent": state.intent,
                    "status": "cancelled",
                    "ui_mode": state.ui_mode,
                    "total_duration_ms": self._control.elapsed_ms
                    if self._control
                    else 0,
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
            self._record_incomplete_acceptance(state, exc)
            self._emit(
                AgentEventType.AGENT_END,
                {
                    "intent": state.intent,
                    "status": "failed",
                    "ui_mode": state.ui_mode,
                    "total_duration_ms": self._control.elapsed_ms
                    if self._control
                    else 0,
                },
            )
            raise
        finally:
            temporary = bool(state.browser_context.get("temporary", False))
            if self.run_recorder is not None and not temporary:
                try:
                    self.run_recorder(state, tuple(self.events))
                except Exception:  # noqa: BLE001,S110 - persistence is best effort
                    # Persistence is diagnostic only. Disk/SQLite failures must
                    # not change Agent success, failure, cancellation or safety.
                    pass
            self._event_sink = previous_sink
            self._active_state = previous_state
            self._control = previous_control

    def _record_incomplete_acceptance(self, state, error, *, cancelled=False):
        uncertain = any(event.event_type == AgentEventType.FAILURE and event.payload.get("execution_outcome") == "unknown" for event in self.events)
        status = "cancelled" if cancelled else "unknown" if uncertain else "failed"
        report = {"status": status, "passed": 0, "total": 1, "reason": str(error)[:1000],
            "semantic_quality": "not_assessed", "criteria": [{"criterion_id": "runtime_execution",
                "label": "任务执行完成且结果可确认", "required": True,
                "status": "unknown" if uncertain else "failed", "evidence": {"error_code": type(error).__name__}}]}
        state.browser_context["task_completion"] = report
        self._emit(AgentEventType.TASK_VERIFICATION, report)
