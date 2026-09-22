from __future__ import annotations

import asyncio
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.agent_core.events import AgentEvent
from backend.agent_core.exceptions import AgentPauseRequestedError, AgentRuntimeError
from backend.agent_core.reliability import AgentRunControl
from backend.api.agent import _associate_workspace_result, _state_from_run_request
from backend.api.agent_checkpoint_dependencies import get_agent_checkpoint_service
from backend.api.agent_dependencies import (
    get_agent_conversation_service,
    get_agent_runtime,
)
from backend.api.agent_observability_dependencies import get_agent_trace_store_service
from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
    get_product_agent_service,
    get_reading_selection_resolver,
    get_research_note_service,
    get_research_workspace_service,
    get_translation_service,
)
from backend.api.knowledge_board_dependencies import get_knowledge_board_service
from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.models.agent_run import AgentRunRecord, AgentRunStatus
from backend.models.agent_runtime import AgentRuntimeProfile
from backend.models.agent_tools import AgentRunRequest
from backend.services.agent_run_scheduler import AgentRunScheduler
from backend.services.agent_run_store import (
    AgentRunStore,
    AgentRunStoreConflictError,
    AgentRunStoreNotFoundError,
)
from backend.services.agent_run_worker import AgentRunOutcome

router = APIRouter(prefix="/api/agent/runtime", tags=["agent-runtime-jobs"])
_store: AgentRunStore | None = None
_store_lock = Lock()


def get_agent_run_store() -> AgentRunStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AgentRunStore()
    return _store


def close_agent_run_store() -> None:
    global _store
    with _store_lock:
        store, _store = _store, None
    if store is not None:
        store.close()


StoreDependency = Annotated[AgentRunStore, Depends(get_agent_run_store)]


class AgentRuntimeJobRequest(BaseModel):
    request: AgentRunRequest
    runtime_profile: AgentRuntimeProfile = AgentRuntimeProfile.LONG_TASK


@router.post("/tasks", response_model=AgentRunRecord, status_code=status.HTTP_202_ACCEPTED)
def enqueue_runtime_task(payload: AgentRuntimeJobRequest, store: StoreDependency) -> AgentRunRecord:
    request = payload.request
    if request.temporary or request.resume_run_id or request.retry_task_id:
        raise HTTPException(status_code=400, detail="Only new durable runs can be enqueued")
    if request.confirmed_write_tools:
        raise HTTPException(
            status_code=400,
            detail="One-shot write confirmations cannot be queued for later execution",
        )
    return AgentRunScheduler(store).enqueue(
        goal=request.user_message,
        workspace_id=request.workspace_id,
        runtime_profile=payload.runtime_profile,
        trace_id=request.trace_id or None,
        request_payload=request.model_dump(mode="json"),
    )


@router.get("/runs/{run_id}", response_model=AgentRunRecord)
def get_runtime_run(run_id: str, store: StoreDependency) -> AgentRunRecord:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/cancel", response_model=AgentRunRecord)
def cancel_runtime_run(run_id: str, store: StoreDependency) -> AgentRunRecord:
    try:
        return AgentRunScheduler(store).cancel(run_id)
    except AgentRunStoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@router.post("/runs/{run_id}/pause", response_model=AgentRunRecord)
def pause_runtime_run(run_id: str, store: StoreDependency) -> AgentRunRecord:
    try:
        return AgentRunScheduler(store).pause(run_id)
    except AgentRunStoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except AgentRunStoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/resume", response_model=AgentRunRecord)
def resume_runtime_run(run_id: str, store: StoreDependency) -> AgentRunRecord:
    try:
        return AgentRunScheduler(store).resume(run_id)
    except AgentRunStoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except AgentRunStoreConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=list[AgentEvent])
def get_runtime_events(run_id: str, store: StoreDependency) -> tuple[AgentEvent, ...]:
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return store.list_events(run_id)


@router.get("/runs/{run_id}/result")
def get_runtime_result(run_id: str, store: StoreDependency) -> dict[str, object]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": run.status.value, "result": store.get_run_result(run_id)}


def _build_runtime():
    research_workspace = get_research_workspace_service()
    research_notes = get_research_note_service()
    return get_agent_runtime(
        service=get_product_agent_service(),
        resolver=get_reading_selection_resolver(),
        conversation_service=get_agent_conversation_service(
            get_conversation_store_service(), get_companion_ownership_service()
        ),
        research_service=research_notes,
        translation_service=get_translation_service(),
        trace_store=get_agent_trace_store_service(),
        checkpoint_service=get_agent_checkpoint_service(),
        research_workspace=research_workspace,
        knowledge_workspace=get_knowledge_workspace_service(),
        knowledge_boards=get_knowledge_board_service(),
    )


async def execute_persisted_agent_run(
    run: AgentRunRecord,
    control: AgentRunControl,
    recovering: bool,
    *,
    store: AgentRunStore,
    lease_owner: str,
) -> AgentRunOutcome:
    def execute() -> AgentRunOutcome:
        raw_request = store.get_run_request(run.run_id)
        if not raw_request:
            raise ValueError(f"Run {run.run_id} has no durable request payload")
        request = AgentRunRequest.model_validate(raw_request)
        if recovering:
            blocked = store.prepare_recovery_tool_calls(
                run.run_id, lease_owner=lease_owner
            )
            if blocked:
                return AgentRunOutcome(
                    status=AgentRunStatus.WAITING,
                    result={
                        "code": "write_recovery_blocked",
                        "tool_call_ids": list(blocked),
                    },
                )
        runtime = _build_runtime()
        research_workspace = get_research_workspace_service()
        try:
            state = (
                runtime.restore_checkpoint(run.run_id)
                if recovering
                else _state_from_run_request(
                    request,
                    workspace_service=research_workspace,
                    research_notes=get_research_note_service(),
                )
            )
        except AgentRuntimeError as exc:
            return AgentRunOutcome(
                status=(
                    AgentRunStatus.WAITING
                    if exc.fallback_reason == "write_checkpoint_requires_manual_recovery"
                    else AgentRunStatus.FAILED
                ),
                result={
                    "code": (
                        "write_recovery_blocked"
                        if exc.fallback_reason == "write_checkpoint_requires_manual_recovery"
                        else exc.fallback_reason
                    ),
                    "message": str(exc),
                },
            )
        if recovering and (
            state.task_id != run.task_id or state.trace_id != run.trace_id
        ):
            return AgentRunOutcome(
                status=AgentRunStatus.FAILED,
                result={"code": "checkpoint_identity_mismatch"},
            )

        def record_checkpoint() -> None:
            metadata_loader = getattr(runtime, "checkpoint_metadata", None)
            metadata = metadata_loader(run.run_id) if callable(metadata_loader) else None
            if metadata is not None:
                store.update_checkpoint_metadata(
                    run.run_id,
                    lease_owner=lease_owner,
                    graph_version=str(metadata["graph_version"]),
                    state_schema_version=int(metadata["state_schema_version"]),
                    checkpoint_id=str(metadata["checkpoint_id"]),
                )

        if recovering:
            record_checkpoint()
        state.task_id = run.task_id
        state.run_id = run.run_id
        state.trace_id = run.trace_id
        state.runtime_profile = run.runtime_profile
        state.sync_contract()
        try:
            result = runtime.execute(
                state,
                control=control,
                resume=recovering,
                event_sink=lambda event: store.append_event(event, lease_owner=lease_owner),
            )
        except AgentPauseRequestedError:
            record_checkpoint()
            raise
        record_checkpoint()
        _associate_workspace_result(request, result, research_workspace)
        response_status = str(result.response.get("status", "completed"))
        target = AgentRunStatus.COMPLETED
        if response_status == "confirmation_required":
            target = AgentRunStatus.WAITING
        elif response_status == "cancelled":
            target = AgentRunStatus.CANCELLED
        elif response_status == "failed":
            target = AgentRunStatus.FAILED
        return AgentRunOutcome(
            status=target,
            result={
                "output_text": str(result.response.get("output_text", "")),
                "provider": str(result.response.get("provider", "")),
                "model": str(result.response.get("model", "")),
                "request_id": int(result.response.get("request_id", 0) or 0),
                "conversation_id": result.conversation.conversation_id,
            },
        )

    return await asyncio.to_thread(execute)


__all__ = [
    "AgentRuntimeJobRequest",
    "close_agent_run_store",
    "execute_persisted_agent_run",
    "get_agent_run_store",
    "router",
]
