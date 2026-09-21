from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from threading import Event, Lock
from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.ai.errors import AIConfigurationError, AIError
from backend.api.dependencies import (
    get_companion_chat_service,
    get_companion_ownership_service,
    get_conversation_store_service,
    get_rag_debug_service,
)
from backend.models.companion import (
    CompanionChatStreamCancel,
    CompanionChatStreamStart,
)
from backend.services.companion_chat_service import CompanionChatService
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
    CompanionOwnershipClaim,
)
from backend.services.conversation_grounding_service import save_message_grounding
from backend.services.conversation_store_service import ConversationStoreService
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier
from backend.services.grounded_synthesis_service import evidence_only_grounding_fallback
from backend.services.rag_debug_service import RagDebugService

router = APIRouter(tags=["companion-stream"])
CompanionChatServiceDependency = Annotated[
    CompanionChatService,
    Depends(get_companion_chat_service),
]
ConversationStoreDependency = Annotated[
    ConversationStoreService,
    Depends(get_conversation_store_service),
]
CompanionOwnershipDependency = Annotated[
    CompanionConversationOwnershipService,
    Depends(get_companion_ownership_service),
]
RagDebugDependency = Annotated[
    RagDebugService,
    Depends(get_rag_debug_service),
]

_TERMINAL_EVENT_TYPES = frozenset({"done", "error", "cancelled"})
_STREAM_FLUSH_INTERVAL_SECONDS = 0.25
_STREAM_FLUSH_CHARACTER_STEP = 256
_logger = logging.getLogger(__name__)


def _stream_kwargs(payload: Any) -> dict[str, Any]:
    return {
        "session_id": payload.session_id,
        "user_message": payload.user_message,
        "source_text": payload.source_text,
        "translated_text": payload.translated_text,
        "source_language": payload.source_language,
        "target_language": payload.target_language,
        "resource_url": payload.resource_url,
        "resource_title": payload.resource_title,
        "section_heading": payload.section_heading,
        "context_before": payload.context_before,
        "context_after": payload.context_after,
        "source_kind": payload.source_kind,
        "history": tuple((item.role, item.content) for item in payload.history),
        "request_id": payload.request_id,
        "context_mode": payload.context_mode,
        "knowledge_enabled": payload.knowledge_enabled,
        "knowledge_document_ids": tuple(payload.knowledge_document_ids),
    }


def _begin_exchange(store: ConversationStoreService, payload: Any, request_id: int):
    kwargs = {
        "conversation_id": payload.conversation_id,
        "session_id": payload.session_id,
        "user_message": payload.user_message,
        "request_id": request_id,
        "source_text": payload.source_text,
        "translated_text": payload.translated_text,
        "source_language": payload.source_language,
        "target_language": payload.target_language,
        "resource_url": payload.resource_url,
        "resource_title": payload.resource_title,
        "section_heading": payload.section_heading,
        "context_before": payload.context_before,
        "context_after": payload.context_after,
        "source_kind": payload.source_kind,
    }
    context_aware = getattr(store, "begin_exchange_with_context_mode", None)
    if callable(context_aware):
        return context_aware(context_mode=payload.context_mode, **kwargs)
    return store.begin_exchange(**kwargs)


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid streaming chat request."
    return str(errors[0].get("msg") or "Invalid streaming chat request.")


def _incoming_identity(incoming: object) -> tuple[int, str]:
    if not isinstance(incoming, dict):
        return 0, ""
    request = incoming.get("request")
    if not isinstance(request, dict):
        return 0, ""
    request_id = request.get("request_id", 0)
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
        request_id = 0
    conversation_id = str(request.get("conversation_id", ""))[:128]
    return request_id, conversation_id


def _error_code(exc: Exception) -> str:
    if isinstance(exc, AIConfigurationError):
        return "configuration"
    if isinstance(exc, AIError):
        return "provider"
    return "internal"


def _consume_background_task(task: asyncio.Task[None]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        task.result()


def _effective_owner_id(payload: Any) -> str:
    explicit = str(getattr(payload, "client_id", "") or "").strip()
    return explicit or f"session:{payload.session_id}"


def _claim_message(claim: CompanionOwnershipClaim) -> str:
    lease = claim.lease
    if claim.reason == "conversation_busy" and lease is not None:
        surface = lease.owner_surface if lease.owner_surface != "unknown" else "another window"
        return f"This conversation is already replying in {surface}."
    if claim.reason in {"duplicate_request", "duplicate_active_request"}:
        return "Duplicate chat request ignored."
    return "Unable to acquire conversation execution ownership."


@router.websocket("/ws/companion/chat")
async def stream_companion_chat(
    websocket: WebSocket,
    service: CompanionChatServiceDependency,
    store: ConversationStoreDependency,
    ownership: CompanionOwnershipDependency,
    rag_debug: RagDebugDependency,
) -> None:
    await websocket.accept()
    cancel_event = Event()
    producer_task: asyncio.Task[None] | None = None
    sender_task: asyncio.Task[str] | None = None
    receiver_task: asyncio.Task[str] | None = None
    assistant_message_id = ""
    conversation_id = ""
    request_id = 0
    owner_id = ""
    ownership_acquired = False
    terminal_lock = Lock()
    terminal_committed = False
    latest_text_lock = Lock()
    latest_text = ""

    def current_text() -> str:
        with latest_text_lock:
            return latest_text

    def update_latest(value: str) -> None:
        nonlocal latest_text
        with latest_text_lock:
            latest_text = value

    def commit_terminal(
        terminal_status: str,
        *,
        content: str | None = None,
        provider: str = "",
        model: str = "",
        error_code: str = "",
    ) -> bool:
        nonlocal terminal_committed
        with terminal_lock:
            if terminal_committed or not assistant_message_id:
                return False
            store.finalize_message(
                assistant_message_id,
                status=terminal_status,
                content=current_text() if content is None else content,
                provider=provider,
                model=model,
                error_code=error_code,
            )
            terminal_committed = True
            return True

    try:
        try:
            incoming = await websocket.receive_json()
        except WebSocketDisconnect:
            return

        try:
            start = CompanionChatStreamStart.model_validate(incoming)
        except ValidationError as exc:
            invalid_request_id, invalid_conversation_id = _incoming_identity(incoming)
            await websocket.send_json(
                {
                    "type": "error",
                    "request_id": invalid_request_id,
                    "conversation_id": invalid_conversation_id,
                    "message_id": "",
                    "code": "invalid_request",
                    "message": _validation_message(exc),
                }
            )
            return

        payload = start.request
        request_id = payload.request_id
        owner_id = _effective_owner_id(payload)
        requested_conversation_id = str(payload.conversation_id or "").strip()

        if requested_conversation_id:
            claim = ownership.acquire(
                requested_conversation_id,
                owner_id=owner_id,
                owner_surface=payload.client_surface,
                request_id=request_id,
            )
            if not claim.acquired:
                await websocket.send_json(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "conversation_id": requested_conversation_id,
                        "message_id": "",
                        "code": claim.reason,
                        "message": _claim_message(claim),
                    }
                )
                return
            ownership_acquired = True
            conversation_id = requested_conversation_id

        try:
            exchange = _begin_exchange(store, payload, request_id)
        except (OSError, ValueError) as exc:
            await websocket.send_json(
                {
                    "type": "error",
                    "request_id": request_id,
                    "conversation_id": payload.conversation_id,
                    "message_id": "",
                    "code": "conversation_store",
                    "message": str(exc) or "Unable to persist AI Chat request.",
                }
            )
            return

        conversation_id = exchange.conversation_id
        assistant_message_id = exchange.assistant_message_id

        if not ownership_acquired:
            claim = ownership.acquire(
                conversation_id,
                owner_id=owner_id,
                owner_surface=payload.client_surface,
                request_id=request_id,
            )
            if not claim.acquired:
                store.finalize_message(
                    assistant_message_id,
                    status="error",
                    content="",
                    error_code=claim.reason,
                )
                terminal_committed = True
                await websocket.send_json(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message_id": assistant_message_id,
                        "code": claim.reason,
                        "message": _claim_message(claim),
                    }
                )
                return
            ownership_acquired = True

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        await websocket.send_json(
            {
                "type": "accepted",
                "request_id": request_id,
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "user_message_id": exchange.user_message_id,
            }
        )

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def produce() -> None:
            accumulated: list[str] = []
            persisted_length = 0
            last_flush = monotonic()
            try:
                stream_kwargs = _stream_kwargs(payload)

                def emit_phase(phase: str, plan: Any) -> None:
                    route = getattr(getattr(plan, "route", ""), "value", "")
                    emit(
                        {
                            "type": "phase",
                            "phase": phase,
                            "route": str(route or ""),
                            "request_id": request_id,
                            "conversation_id": conversation_id,
                            "message_id": assistant_message_id,
                        }
                    )

                prepared = service.prepare_execution(
                    query=payload.user_message,
                    knowledge_enabled=payload.knowledge_enabled,
                    document_ids=tuple(payload.knowledge_document_ids),
                    history=tuple(
                        (item.role, item.content) for item in payload.history
                    ),
                    context_mode=payload.context_mode,
                    source_text=payload.source_text,
                    phase_callback=emit_phase,
                )
                grounding = prepared.grounding
                evidence_route = (
                    prepared.plan.grounding_policy is GroundingPolicy.EVIDENCE
                )
                companion_trace_id = ""
                try:
                    companion_trace_id = rag_debug.record_companion_route(
                        request_id=request_id,
                        conversation_id=conversation_id,
                        query=payload.user_message,
                        knowledge_enabled=payload.knowledge_enabled,
                        document_ids=tuple(payload.knowledge_document_ids),
                        route=prepared.plan.route.value,
                        route_reason=prepared.plan.reason,
                        grounding_policy=prepared.plan.grounding_policy.value,
                        retrieval_skipped=not prepared.plan.use_knowledge,
                        verification_skipped=not evidence_route,
                        catalog_document_count=prepared.catalog_document_count,
                        retrieval=dict(prepared.grounding.debug_metadata or {}),
                        evidence=[
                            item.model_dump(mode="json")
                            for item in prepared.grounding.evidence
                        ],
                        citations=[
                            item.model_dump(mode="json")
                            for item in prepared.grounding.citations
                        ],
                    )
                except Exception:  # noqa: BLE001 - observability must not break chat
                    _logger.exception("Failed to record Companion routing trace.")
                if prepared.tool_name:
                    stream_kwargs["tool_name"] = prepared.tool_name
                    stream_kwargs["tool_context"] = prepared.tool_context
                stream_kwargs.pop("knowledge_enabled", None)
                stream_kwargs.pop("knowledge_document_ids", None)
                direct_output = str(prepared.direct_output_text or "")
                response_provider = "local" if direct_output else service.provider_name
                response_model = "deterministic" if direct_output else service.model
                stream_parts = (
                    (direct_output,)
                    if direct_output
                    else service.stream(**stream_kwargs)
                )
                emit_phase("generating", prepared.plan)
                for delta in stream_parts:
                    if cancel_event.is_set():
                        return
                    ownership.touch(
                        conversation_id,
                        owner_id=owner_id,
                        request_id=request_id,
                    )
                    accumulated.append(delta)
                    text = "".join(accumulated)
                    if evidence_route:
                        # Evidence-grounded output is provisional until deterministic
                        # grounding verification completes. The desktop runtime
                        # renders accumulated_text as a replaceable streaming
                        # draft, while persistence remains untouched until the
                        # authoritative verified/fallback result is available.
                        emit(
                            {
                                "type": "delta",
                                "request_id": request_id,
                                "conversation_id": conversation_id,
                                "message_id": assistant_message_id,
                                "delta": delta,
                                "accumulated_text": text,
                            }
                        )
                        continue
                    update_latest(text)
                    now = monotonic()
                    if (
                        len(text) - persisted_length >= _STREAM_FLUSH_CHARACTER_STEP
                        or now - last_flush >= _STREAM_FLUSH_INTERVAL_SECONDS
                    ):
                        store.update_stream(assistant_message_id, text)
                        persisted_length = len(text)
                        last_flush = now
                    emit(
                        {
                            "type": "delta",
                            "request_id": request_id,
                            "conversation_id": conversation_id,
                            "message_id": assistant_message_id,
                            "delta": delta,
                            "accumulated_text": text,
                        }
                    )

                if cancel_event.is_set():
                    return
                generated_text = "".join(accumulated)
                text = generated_text
                update_latest(text)
                grounding_fallback = (
                    str(getattr(grounding, "fallback_reason", "") or "")
                    if grounding
                    else ""
                )
                grounding_evidence = tuple(getattr(grounding, "evidence", ()) or ())
                grounding_citations = tuple(getattr(grounding, "citations", ()) or ())
                verification_payload: dict[str, Any] | None = None
                if evidence_route:
                    emit_phase("verifying", prepared.plan)
                    verification = AgentClaimEvidenceVerifier().verify(
                        output_text=text,
                        evidence=grounding_evidence,
                        citations=grounding_citations,
                    )
                    verification_payload = {
                        "passed": verification.passed,
                        "strict_passed": verification.strict_passed,
                        "partial_grounding": verification.partial_grounding,
                        "claim_count": verification.claim_count,
                        "cited_claim_count": verification.cited_claim_count,
                        "supported_claim_count": verification.supported_claim_count,
                        "unsupported_claim_count": verification.unsupported_claim_count,
                        "invalid_citation_count": verification.invalid_citation_count,
                        "citation_coverage": verification.citation_coverage,
                        "support_rate": verification.support_rate,
                        "paragraph_count": verification.paragraph_count,
                        "cited_paragraph_count": verification.cited_paragraph_count,
                        "supported_paragraph_count": verification.supported_paragraph_count,
                        "paragraph_citation_coverage": verification.paragraph_citation_coverage,
                        "paragraph_support_rate": verification.paragraph_support_rate,
                        "reason_codes": list(verification.reason_codes),
                    }
                    if not verification.passed:
                        text = evidence_only_grounding_fallback(
                            evidence=list(grounding_evidence),
                            citations=list(grounding_citations),
                        )
                        grounding_fallback = "; ".join(
                            part
                            for part in (
                                grounding_fallback,
                                "grounding_verification_failed:",
                                ",".join(verification.reason_codes),
                            )
                            if part
                        )
                    update_latest(text)
                    store.update_stream(assistant_message_id, text)
                    if companion_trace_id:
                        try:
                            rag_debug.update_companion_verification(
                                companion_trace_id,
                                verification=verification_payload,
                                fallback_applied=text != generated_text,
                            )
                        except Exception:  # noqa: BLE001 - observability must not break chat
                            _logger.exception(
                                "Failed to update Companion verification trace."
                            )
                    if text != generated_text:
                        # accumulated_text is authoritative for delta rendering,
                        # so a hard fallback atomically replaces the provisional
                        # draft instead of appending to it.
                        emit(
                            {
                                "type": "delta",
                                "request_id": request_id,
                                "conversation_id": conversation_id,
                                "message_id": assistant_message_id,
                                "delta": "",
                                "accumulated_text": text,
                            }
                        )
                commit_terminal(
                    "complete",
                    content=text,
                    provider=response_provider,
                    model=response_model,
                )
                if evidence_route:
                    try:
                        save_message_grounding(
                            store.storage_path,
                            assistant_message_id,
                            knowledge_enabled=True,
                            knowledge_fallback_reason=grounding_fallback,
                            evidence=list(grounding_evidence),
                            citations=list(grounding_citations),
                        )
                    except Exception:  # noqa: BLE001 - live answer must survive metadata persistence failure
                        _logger.exception(
                            "Failed to persist knowledge grounding for message %s",
                            assistant_message_id,
                        )
                emit(
                    {
                        "type": "done",
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message_id": assistant_message_id,
                        "output_text": text,
                        "provider": response_provider,
                        "model": response_model,
                        "knowledge_enabled": payload.knowledge_enabled,
                        "knowledge_fallback_reason": grounding_fallback,
                        "evidence": [
                            item.model_dump(mode="json") for item in grounding_evidence
                        ],
                        "citations": [
                            item.model_dump(mode="json") for item in grounding_citations
                        ],
                        "grounding_verification": verification_payload,
                    }
                )
            except Exception as exc:
                if cancel_event.is_set():
                    return
                code = _error_code(exc)
                commit_terminal(
                    "error",
                    provider=service.provider_name,
                    model=service.model,
                    error_code=code,
                )
                emit(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message_id": assistant_message_id,
                        "code": code,
                        "message": str(exc) or "AI chat streaming failed.",
                    }
                )

        async def send_events() -> str:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if event.get("type") in _TERMINAL_EVENT_TYPES:
                    return str(event.get("type"))

        async def receive_control() -> str:
            while True:
                try:
                    control = await websocket.receive_json()
                except WebSocketDisconnect:
                    cancel_event.set()
                    return "disconnect"

                if not isinstance(control, dict) or control.get("type") != "cancel":
                    continue
                try:
                    cancel = CompanionChatStreamCancel.model_validate(control)
                except ValidationError:
                    continue
                if cancel.request_id != request_id:
                    continue

                cancel_event.set()
                commit_terminal("cancelled", error_code="user_cancelled")
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                await queue.put(
                    {
                        "type": "cancelled",
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message_id": assistant_message_id,
                    }
                )
                return "cancel"

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
            if control_result == "cancel":
                with suppress(asyncio.TimeoutError, WebSocketDisconnect):
                    await asyncio.wait_for(sender_task, timeout=1.0)
            else:
                sender_task.cancel()
        else:
            receiver_task.cancel()
    finally:
        cancel_event.set()
        commit_terminal("cancelled", error_code="transport_closed")
        if ownership_acquired and conversation_id and owner_id:
            ownership.release(
                conversation_id,
                owner_id=owner_id,
                request_id=request_id,
            )
        for task in (sender_task, receiver_task):
            if task is not None and not task.done():
                task.cancel()
