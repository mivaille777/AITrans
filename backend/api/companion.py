import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.errors import AIConfigurationError, AIError
from backend.api.dependencies import (
    get_companion_chat_service,
    get_companion_handoff_service,
    get_companion_ownership_service,
    get_rag_debug_service,
)
from backend.models.companion import (
    CompanionChatOwnershipResponse,
    CompanionChatRequest,
    CompanionChatResponse,
    CompanionChatStatusResponse,
    CompanionDismissRequest,
    CompanionHandoffEnvelope,
    CompanionHandoffRequest,
    CompanionHandoffResponse,
)
from backend.models.companion_routing import GroundingPolicy
from backend.services.companion_chat_service import (
    CompanionChatService,
    CompanionPreparedExecution,
)
from backend.services.companion_handoff_service import (
    CompanionHandoffService,
    CompanionHandoffState,
)
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)

router = APIRouter(prefix="/api/companion", tags=["companion"])
CompanionHandoffServiceDependency = Annotated[
    CompanionHandoffService,
    Depends(get_companion_handoff_service),
]
CompanionChatServiceDependency = Annotated[
    CompanionChatService,
    Depends(get_companion_chat_service),
]
CompanionOwnershipServiceDependency = Annotated[
    CompanionConversationOwnershipService,
    Depends(get_companion_ownership_service),
]


def _handoff_response(state: CompanionHandoffState) -> CompanionHandoffResponse:
    return CompanionHandoffResponse(
        revision=state.revision,
        handoff_id=state.handoff_id,
        created_at=state.created_at,
        source_text=state.source_text,
        translated_text=state.translated_text,
        source_language=state.source_language,
        target_language=state.target_language,
        resource_url=state.resource_url,
        resource_title=state.resource_title,
        section_heading=state.section_heading,
        context_before=state.context_before,
        context_after=state.context_after,
        source_kind=state.source_kind,
        conversation_id=state.conversation_id,
        ai_content=state.ai_content,
        ai_action=state.ai_action,
        suggested_prompt=state.suggested_prompt,
        knowledge_enabled=state.knowledge_enabled,
        knowledge_document_ids=list(state.knowledge_document_ids),
    )


@router.get("/handoff", response_model=CompanionHandoffEnvelope)
def companion_handoff(
    service: CompanionHandoffServiceDependency,
) -> CompanionHandoffEnvelope:
    state = service.snapshot()
    return CompanionHandoffEnvelope(
        handoff=_handoff_response(state) if state is not None else None
    )


@router.post("/handoff", response_model=CompanionHandoffResponse)
def create_companion_handoff(
    payload: CompanionHandoffRequest,
    service: CompanionHandoffServiceDependency,
) -> CompanionHandoffResponse:
    try:
        state = service.create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _handoff_response(state)


@router.post("/handoff/dismiss", response_model=CompanionHandoffEnvelope)
def dismiss_companion_handoff(
    payload: CompanionDismissRequest,
    service: CompanionHandoffServiceDependency,
) -> CompanionHandoffEnvelope:
    state = service.clear(handoff_id=payload.handoff_id)
    return CompanionHandoffEnvelope(
        handoff=_handoff_response(state) if state is not None else None
    )


@router.get("/chat/status", response_model=CompanionChatStatusResponse)
def companion_chat_status(
    service: CompanionChatServiceDependency,
) -> CompanionChatStatusResponse:
    available, provider, model, detail = service.status()
    return CompanionChatStatusResponse(
        available=available,
        provider=provider,
        model=model,
        detail=detail,
    )


@router.get(
    "/chat/ownership/{conversation_id}",
    response_model=CompanionChatOwnershipResponse,
)
def companion_chat_ownership(
    conversation_id: str,
    service: CompanionOwnershipServiceDependency,
) -> CompanionChatOwnershipResponse:
    lease = service.snapshot(conversation_id)
    if lease is None:
        return CompanionChatOwnershipResponse(
            conversation_id=conversation_id,
            busy=False,
            stale_after_seconds=service.stale_after_seconds,
        )
    return CompanionChatOwnershipResponse(
        conversation_id=lease.conversation_id,
        busy=True,
        owner_id=lease.owner_id,
        owner_surface=lease.owner_surface,
        request_id=lease.request_id,
        stale_after_seconds=service.stale_after_seconds,
    )


@router.post("/chat", response_model=CompanionChatResponse)
def send_companion_chat(
    payload: CompanionChatRequest,
    service: CompanionChatServiceDependency,
) -> CompanionChatResponse:
    trace_service = None
    trace_id = ""
    try:
        trace_service = get_rag_debug_service()
        trace_id = trace_service.record_companion_route(
            request_id=payload.request_id, conversation_id=payload.conversation_id,
            query=payload.user_message, knowledge_enabled=payload.knowledge_enabled,
            document_ids=tuple(payload.knowledge_document_ids), route="pending", route_reason="",
            grounding_policy="pending", retrieval_skipped=True, verification_skipped=True,
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed to start HTTP Companion trace.")

    def record_phase(stage: str, _plan: Any = None, *, terminal: str = "active", metadata: dict | None = None) -> None:
        if trace_service is not None and trace_id:
            try:
                trace_service.record_companion_event(
                    trace_id, stage=stage, status=terminal, metadata=metadata,
                )
            except Exception:
                logging.getLogger(__name__).exception("Failed to record HTTP Companion trace.")

    def record_prepared(prepared: CompanionPreparedExecution) -> None:
        if trace_service is not None and trace_id:
            try:
                trace_service.record_companion_route(
                    trace_id=trace_id, request_id=payload.request_id,
                    conversation_id=payload.conversation_id, query=payload.user_message,
                    knowledge_enabled=payload.knowledge_enabled,
                    document_ids=tuple(payload.knowledge_document_ids),
                    route=prepared.plan.route.value, route_reason=prepared.plan.reason,
                    grounding_policy=prepared.plan.grounding_policy.value,
                    retrieval_skipped=not prepared.plan.use_knowledge,
                    verification_skipped=prepared.plan.grounding_policy is not GroundingPolicy.EVIDENCE,
                    catalog_document_count=prepared.catalog_document_count,
                    retrieval=dict(prepared.grounding.debug_metadata or {}),
                    evidence=[item.model_dump(mode="json") for item in prepared.grounding.evidence],
                    citations=[item.model_dump(mode="json") for item in prepared.grounding.citations],
                )
            except Exception:
                logging.getLogger(__name__).exception("Failed to record HTTP Companion preparation.")

    def record_verification(verification: dict, fallback_applied: bool) -> None:
        if trace_service is not None and trace_id:
            try:
                trace_service.update_companion_verification(
                    trace_id, verification=verification, fallback_applied=fallback_applied,
                )
            except Exception:
                logging.getLogger(__name__).exception("Failed to record HTTP Companion verification.")

    record_phase("preparing")
    try:
        result = service.send(
            session_id=payload.session_id,
            user_message=payload.user_message,
            source_text=payload.source_text,
            translated_text=payload.translated_text,
            source_language=payload.source_language,
            target_language=payload.target_language,
            resource_url=payload.resource_url,
            resource_title=payload.resource_title,
            section_heading=payload.section_heading,
            context_before=payload.context_before,
            context_after=payload.context_after,
            source_kind=payload.source_kind,
            history=tuple((item.role, item.content) for item in payload.history),
            request_id=payload.request_id,
            context_mode=payload.context_mode,
            knowledge_access_policy=payload.knowledge_access_policy,
            knowledge_enabled=payload.knowledge_enabled,
            knowledge_document_ids=tuple(payload.knowledge_document_ids),
            **({"trace_id": trace_id or None, "phase_callback": record_phase,
                "prepared_callback": record_prepared, "verification_callback": record_verification}
               if isinstance(service, CompanionChatService) else {}),
        )
    except AIConfigurationError as exc:
        record_phase("answer", terminal="error", metadata={"error_code": "configuration"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AIError as exc:
        record_phase("answer", terminal="error", metadata={"error_code": "provider"})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception:
        record_phase("answer", terminal="error", metadata={"error_code": "internal"})
        raise

    record_phase("answer", terminal="complete", metadata={"provider": result.provider,
        "model": result.model, "output_characters": len(result.output_text)})

    return CompanionChatResponse(
        conversation_id=payload.conversation_id,
        session_id=result.session_id,
        user_message=result.user_message,
        output_text=result.output_text,
        provider=result.provider,
        model=result.model,
        request_id=result.request_id,
        knowledge_enabled=getattr(result, "knowledge_enabled", False),
        knowledge_access_policy=getattr(result, "knowledge_access_policy", payload.knowledge_access_policy),
        knowledge_decision=getattr(result, "knowledge_decision", None),
        knowledge_retrieved=getattr(result, "knowledge_retrieved", False),
        knowledge_document_count=getattr(result, "knowledge_document_count", 0),
        knowledge_chunk_count=getattr(result, "knowledge_chunk_count", 0),
        knowledge_fallback_reason=getattr(result, "knowledge_fallback_reason", ""),
        knowledge_recovery=getattr(result, "knowledge_recovery", {}),
        evidence=list(getattr(result, "evidence", ())),
        citations=list(getattr(result, "citations", ())),
    )
