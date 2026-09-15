from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from app.ai.errors import AIConfigurationError, AIError
from backend.agent_core.events import AgentEvent
from backend.agent_core.exceptions import (
    AgentBudgetExceededError,
    AgentCancelledError,
    AgentRuntimeError,
    AgentToolTimeoutError,
)
from backend.agent_core.reliability import AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.api.agent_dependencies import get_agent_runtime
from backend.api.dependencies import (
    get_agent_tool_registry,
    get_research_note_service,
    get_research_workspace_service,
)
from backend.models.agent_tools import (
    AgentPlan,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunTraceResponse,
    AgentToolCatalogResponse,
    AgentToolDefinition,
    AgentToolExecuteRequest,
    AgentToolExecuteResponse,
    AgentTraceEvent,
)
from backend.services.agent_conversation_service import AgentConversationBusyError
from backend.services.agent_tool_registry import (
    AgentToolExecutionResult,
    AgentToolRegistry,
)
from backend.services.research_note_service import ResearchNoteService, research_source_id
from backend.services.research_workspace_service import ResearchWorkspaceService

router = APIRouter(prefix="/api/agent", tags=["agent"])
AgentToolRegistryDependency = Annotated[
    AgentToolRegistry,
    Depends(get_agent_tool_registry),
]
AgentRuntimeDependency = Annotated[
    AgentRuntime,
    Depends(get_agent_runtime),
]
ResearchWorkspaceDependency = Annotated[
    ResearchWorkspaceService,
    Depends(get_research_workspace_service),
]
ResearchNoteDependency = Annotated[
    ResearchNoteService,
    Depends(get_research_note_service),
]


def _tool_response(result: AgentToolExecutionResult) -> AgentToolExecuteResponse:
    return AgentToolExecuteResponse(
        tool_name=result.tool_name,
        output_text=result.output_text,
        effect=result.effect,
        provider=result.provider,
        model=result.model,
        request_id=result.request_id,
        data=result.data or {},
    )


def _state_tool_response(result: dict[str, Any]) -> AgentToolExecuteResponse:
    payload = dict(result)
    payload["data"] = dict(payload.get("data") or {})
    return AgentToolExecuteResponse.model_validate(payload)


def _workspace_research_source_ids(
    note_ids: tuple[str, ...],
    research_notes: ResearchNoteService,
) -> list[str]:
    source_ids: list[str] = []
    seen: set[str] = set()
    for note_id in note_ids:
        note = research_notes.get(note_id)
        if note is None:
            continue
        source_id = research_source_id(note)
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(source_id)
        if len(source_ids) >= 100:
            break
    return source_ids


def _empty_workspace_scope_id(workspace_id: str, kind: str) -> str:
    """Return an impossible persisted-resource id that keeps an empty scope closed.

    Existing retrieval Tools interpret an empty list as global scope. A selected
    Research Workspace must never widen to global just because it currently has
    zero members, so the trusted API boundary supplies a non-empty sentinel that
    cannot match generated document/source identifiers.
    """

    return f"__workspace_empty_scope__:{kind}:{workspace_id}"


def _state_from_run_request(
    payload: AgentRunRequest,
    *,
    workspace_service: ResearchWorkspaceService | None = None,
    research_notes: ResearchNoteService | None = None,
) -> AgentState:
    context = payload.model_dump(
        exclude={
            "session_id",
            "trace_id",
            "user_message",
            "source_text",
        }
    )
    workspace_id = payload.workspace_id.strip()
    if workspace_id:
        if workspace_service is None or research_notes is None:
            raise ValueError("Research workspace context is unavailable.")
        workspace = workspace_service.get(workspace_id)
        if workspace is None:
            raise ValueError("Research workspace not found.")
        # A selected Workspace is authoritative. Client-side temporary scopes are
        # ignored so the Agent receives the persisted research-project context.
        # Empty project membership must remain an empty scope rather than falling
        # through to the legacy global-search meaning of an empty list.
        document_ids = list(workspace.document_ids)
        research_source_ids = _workspace_research_source_ids(
            workspace.note_ids,
            research_notes,
        )
        context["workspace_id"] = workspace_id
        context["knowledge_document_ids"] = document_ids or [
            _empty_workspace_scope_id(workspace_id, "document")
        ]
        context["research_source_ids"] = research_source_ids or [
            _empty_workspace_scope_id(workspace_id, "research")
        ]

    kwargs: dict[str, Any] = {
        "session_id": payload.session_id,
        "user_input": payload.user_message,
        "selected_text": payload.source_text,
        "browser_context": context,
    }
    if payload.trace_id.strip():
        kwargs["trace_id"] = payload.trace_id.strip()
    return AgentState(**kwargs)


def _associate_workspace_result(
    payload: AgentRunRequest,
    state: AgentState,
    workspace_service: ResearchWorkspaceService | None,
) -> None:
    workspace_id = payload.workspace_id.strip()
    if not workspace_id or workspace_service is None:
        return
    if workspace_service.get(workspace_id) is None:
        return

    conversation_id = state.conversation.conversation_id.strip()
    if conversation_id:
        workspace_service.attach_conversation(workspace_id, conversation_id)

    for raw_result in reversed(state.tool_results):
        if str(raw_result.get("tool_name", "") or "") != "save_research_note":
            continue
        data = raw_result.get("data", {})
        if not isinstance(data, dict):
            continue
        note_id = str(data.get("note_id", "") or "").strip()
        if note_id:
            workspace_service.attach_note(workspace_id, note_id)
        break


def _run_response(state: AgentState) -> AgentRunResponse:
    response = state.response
    tool_result = (
        _state_tool_response(state.tool_results[-1]) if state.tool_results else None
    )
    multi_step = state.plan if state.plan.mode == "multi_step" else None
    compatibility_plan = (
        AgentPlan(
            action="answer",
            user_visible_reason=state.plan.goal or "Completed the multi-step plan.",
        )
        if multi_step is not None
        else AgentPlan.model_validate(state.planned_action)
    )
    return AgentRunResponse(
        status=str(response.get("status", "completed") or "completed"),
        plan=compatibility_plan,
        multi_step_plan=multi_step,
        output_text=str(response.get("output_text", "") or ""),
        provider=str(response.get("provider", "") or ""),
        model=str(response.get("model", "") or ""),
        request_id=max(0, int(response.get("request_id", 0) or 0)),
        conversation_id=state.conversation.conversation_id,
        tool_result=tool_result,
        evidence=state.evidence,
        citations=state.citations,
    )


def _execute_runtime(
    payload: AgentRunRequest,
    runtime: AgentRuntime,
    *,
    workspace_service: ResearchWorkspaceService | None = None,
    research_notes: ResearchNoteService | None = None,
) -> AgentState:
    try:
        state = _state_from_run_request(
            payload,
            workspace_service=workspace_service,
            research_notes=research_notes,
        )
        result = runtime.execute(state)
        _associate_workspace_result(payload, result, workspace_service)
        return result
    except AgentConversationBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (AgentBudgetExceededError, AgentToolTimeoutError) as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _trace_event(sequence: int, event: AgentEvent) -> AgentTraceEvent:
    return AgentTraceEvent(
        sequence=sequence,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        run_id=event.run_id,
        trace_id=event.trace_id,
        elapsed_ms=event.elapsed_ms,
        payload=event.payload,
    )


def _trace_response(state: AgentState, runtime: AgentRuntime) -> AgentRunTraceResponse:
    total_duration_ms = runtime.events[-1].elapsed_ms if runtime.events else 0
    return AgentRunTraceResponse(
        run_id=state.run_id,
        trace_id=state.trace_id,
        session_id=state.session_id or "",
        ui_mode=state.ui_mode,
        total_duration_ms=total_duration_ms,
        run=_run_response(state),
        events=[_trace_event(index, event) for index, event in enumerate(runtime.events)],
    )


def _stream_error_code(exc: Exception) -> str:
    if isinstance(exc, AgentCancelledError):
        return "cancelled"
    if isinstance(exc, AgentConversationBusyError):
        return exc.reason
    if isinstance(exc, AgentBudgetExceededError):
        return "budget_exceeded"
    if isinstance(exc, AgentToolTimeoutError):
        return "tool_timeout"
    if isinstance(exc, AIConfigurationError):
        return "configuration"
    if isinstance(exc, (AIError, AgentRuntimeError)):
        return "provider_or_runtime"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return "internal"


def _consume_background_task(task: asyncio.Task[None]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        task.result()


@router.get("/tools", response_model=AgentToolCatalogResponse)
def list_agent_tools(registry: AgentToolRegistryDependency) -> AgentToolCatalogResponse:
    return AgentToolCatalogResponse(
        tools=[AgentToolDefinition(**asdict(spec)) for spec in registry.list_tools()]
    )


@router.post("/tools/{tool_name}/execute", response_model=AgentToolExecuteResponse)
def execute_agent_tool(
    tool_name: str,
    payload: AgentToolExecuteRequest,
    registry: AgentToolRegistryDependency,
) -> AgentToolExecuteResponse:
    try:
        result = registry.execute(tool_name, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return _tool_response(result)


@router.post("/run", response_model=AgentRunResponse)
def run_product_agent(
    payload: AgentRunRequest,
    runtime: AgentRuntimeDependency,
    workspace_service: ResearchWorkspaceDependency = None,
    research_notes: ResearchNoteDependency = None,
) -> AgentRunResponse:
    return _run_response(
        _execute_runtime(
            payload,
            runtime,
            workspace_service=workspace_service,
            research_notes=research_notes,
        )
    )


@router.post("/run/trace", response_model=AgentRunTraceResponse)
def run_product_agent_trace(
    payload: AgentRunRequest,
    runtime: AgentRuntimeDependency,
    workspace_service: ResearchWorkspaceDependency = None,
    research_notes: ResearchNoteDependency = None,
) -> AgentRunTraceResponse:
    state = _execute_runtime(
        payload,
        runtime,
        workspace_service=workspace_service,
        research_notes=research_notes,
    )
    return _trace_response(state, runtime)


@router.websocket("/stream")
async def stream_product_agent(
    websocket: WebSocket,
    runtime: AgentRuntimeDependency,
    workspace_service: ResearchWorkspaceDependency,
    research_notes: ResearchNoteDependency,
) -> None:
    """Stream bounded Agent lifecycle events with cooperative cancellation."""

    await websocket.accept()
    producer_task: asyncio.Task[None] | None = None
    sender_task: asyncio.Task[str] | None = None
    receiver_task: asyncio.Task[str] | None = None
    control = AgentRunControl()

    try:
        try:
            incoming = await websocket.receive_json()
        except WebSocketDisconnect:
            return

        if not isinstance(incoming, dict) or incoming.get("type") != "start":
            await websocket.send_json(
                {
                    "type": "error",
                    "request_id": 0,
                    "session_id": "",
                    "run_id": "",
                    "trace_id": "",
                    "code": "invalid_request",
                    "message": "Expected an Agent stream start request.",
                }
            )
            return

        try:
            payload = AgentRunRequest.model_validate(incoming.get("request"))
            state = _state_from_run_request(
                payload,
                workspace_service=workspace_service,
                research_notes=research_notes,
            )
        except (ValidationError, ValueError) as exc:
            message = str(exc)
            if isinstance(exc, ValidationError) and exc.errors():
                message = str(exc.errors()[0].get("msg") or "Invalid Agent request.")
            await websocket.send_json(
                {
                    "type": "error",
                    "request_id": 0,
                    "session_id": "",
                    "run_id": "",
                    "trace_id": "",
                    "code": "invalid_request",
                    "message": message or "Invalid Agent request.",
                }
            )
            return

        request_id = payload.request_id
        session_id = payload.session_id
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        await websocket.send_json(
            {
                "type": "accepted",
                "request_id": request_id,
                "session_id": session_id,
                "run_id": state.run_id,
                "trace_id": state.trace_id,
            }
        )

        def enqueue(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def observe(event: AgentEvent) -> None:
            sequence = max(0, len(runtime.events) - 1)
            enqueue(
                {
                    "type": "activity",
                    "request_id": request_id,
                    "session_id": session_id,
                    "run_id": state.run_id,
                    "trace_id": state.trace_id,
                    "event": _trace_event(sequence, event).model_dump(mode="json"),
                }
            )

        def produce() -> None:
            try:
                result_state = runtime.execute(
                    state,
                    event_sink=observe,
                    control=control,
                )
                _associate_workspace_result(payload, result_state, workspace_service)
                trace = _trace_response(result_state, runtime)
                enqueue(
                    {
                        "type": "done",
                        "request_id": request_id,
                        "session_id": session_id,
                        "run_id": result_state.run_id,
                        "trace_id": result_state.trace_id,
                        "trace": trace.model_dump(mode="json"),
                    }
                )
            except AgentCancelledError as exc:
                enqueue(
                    {
                        "type": "cancelled",
                        "request_id": request_id,
                        "session_id": session_id,
                        "run_id": state.run_id,
                        "trace_id": state.trace_id,
                        "message": str(exc) or "Agent run cancelled.",
                    }
                )
            except Exception as exc:
                enqueue(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "session_id": session_id,
                        "run_id": state.run_id,
                        "trace_id": state.trace_id,
                        "code": _stream_error_code(exc),
                        "fallback_reason": str(
                            getattr(exc, "fallback_reason", "") or "no_safe_fallback"
                        ),
                        "message": str(exc) or "Agent execution failed.",
                    }
                )

        async def send_events() -> str:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if event.get("type") in {"done", "error", "cancelled"}:
                    return str(event.get("type"))

        async def receive_control() -> str:
            while True:
                try:
                    message = await websocket.receive_json()
                except WebSocketDisconnect:
                    control.cancel()
                    return "disconnect"
                if not isinstance(message, dict) or message.get("type") != "cancel":
                    continue
                incoming_request_id = message.get("request_id", -1)
                if incoming_request_id != request_id:
                    continue
                control.cancel()
                await queue.put(
                    {
                        "type": "cancel_requested",
                        "request_id": request_id,
                        "session_id": session_id,
                        "run_id": state.run_id,
                        "trace_id": state.trace_id,
                    }
                )
                return "cancel_requested"

        producer_task = asyncio.create_task(asyncio.to_thread(produce))
        producer_task.add_done_callback(_consume_background_task)
        sender_task = asyncio.create_task(send_events())
        receiver_task = asyncio.create_task(receive_control())

        done, _pending = await asyncio.wait(
            {sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if receiver_task in done:
            control_result = receiver_task.result()
            if control_result == "disconnect":
                sender_task.cancel()
                return
            with suppress(WebSocketDisconnect):
                await sender_task
        else:
            receiver_task.cancel()
    finally:
        control.cancel()
        for task in (sender_task, receiver_task):
            if task is not None and not task.done():
                task.cancel()