from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from backend.services.execution_result_service import load_execution_results
from backend.services.sandbox_debug_artifacts import read_manifest_artifact
from backend.services.sandbox_debug_service import SandboxDebugError

from backend.api.dependencies import (
    get_companion_ownership_service,
    get_conversation_store_service,
)
from backend.models.conversations import (
    ConversationContextUpdateRequest,
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationRenameRequest,
    ConversationRewindRequest,
    ConversationSummaryResponse,
)
from backend.models.markdown_export import MarkdownDocument
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.conversation_grounding_service import load_message_grounding
from backend.services.conversation_store_service import (
    ConversationStoreService,
    StoredConversation,
    StoredMessage,
)
from backend.services.markdown_export_service import (
    conversation_markdown,
    load_markdown_export,
    markdown_document,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
ConversationStoreDependency = Annotated[
    ConversationStoreService,
    Depends(get_conversation_store_service),
]
CompanionOwnershipDependency = Annotated[
    CompanionConversationOwnershipService,
    Depends(get_companion_ownership_service),
]


def _message_response(
    service: ConversationStoreService,
    message: StoredMessage,
) -> ConversationMessageResponse:
    grounding = load_message_grounding(service.storage_path, message.message_id)
    return ConversationMessageResponse(
        execution_results=load_execution_results(service.storage_path, message.message_id),
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        request_id=message.request_id,
        role=message.role,
        content=message.content,
        status=message.status,
        provider=message.provider,
        model=message.model,
        error_code=message.error_code,
        knowledge_enabled=grounding.knowledge_enabled,
        knowledge_access_policy=grounding.knowledge_access_policy,
        knowledge_decision=grounding.knowledge_decision,
        knowledge_retrieved=grounding.knowledge_retrieved,
        knowledge_document_count=grounding.knowledge_document_count,
        knowledge_chunk_count=grounding.knowledge_chunk_count,
        knowledge_fallback_reason=grounding.knowledge_fallback_reason,
        knowledge_recovery=grounding.knowledge_recovery,
        evidence=list(grounding.evidence),
        citations=list(grounding.citations),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _context_mode(service: Any, conversation: StoredConversation) -> str:
    resolver = getattr(service, "context_mode", None)
    if callable(resolver):
        value = str(resolver(conversation.conversation_id) or "").strip().lower()
        if value in {"general", "reading"}:
            return value
    return "reading" if conversation.source_text.strip() else "general"


def _summary_response(
    service: Any,
    conversation: StoredConversation,
) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        conversation_id=conversation.conversation_id,
        session_id=conversation.session_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        provider=conversation.provider,
        model=conversation.model,
        context_mode=_context_mode(service, conversation),
        resource_title=conversation.resource_title,
        section_heading=conversation.section_heading,
        source_kind=conversation.source_kind,
    )


def _detail_response(
    service: ConversationStoreService,
    conversation: StoredConversation,
) -> ConversationDetailResponse:
    return ConversationDetailResponse(
        **_summary_response(service, conversation).model_dump(),
        source_text=conversation.source_text,
        translated_text=conversation.translated_text,
        source_language=conversation.source_language,
        target_language=conversation.target_language,
        resource_url=conversation.resource_url,
        context_before=conversation.context_before,
        context_after=conversation.context_after,
        messages=[_message_response(service, message) for message in conversation.messages],
    )


def _assert_conversation_idle(
    ownership: CompanionConversationOwnershipService,
    conversation_id: str,
) -> None:
    lease = ownership.snapshot(conversation_id)
    if lease is None:
        return
    surface = lease.owner_surface if lease.owner_surface != "unknown" else "another window"
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Conversation is currently replying in {surface}.",
    )


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    service: ConversationStoreDependency,
    limit: int = Query(default=30, ge=1, le=50),
) -> ConversationListResponse:
    return ConversationListResponse(
        conversations=[
            _summary_response(service, item)
            for item in service.list_recent(limit=limit)
        ]
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    service: ConversationStoreDependency,
) -> ConversationDetailResponse:
    conversation = service.get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return _detail_response(service, conversation)


@router.get("/{conversation_id}/messages/{message_id}/executions/{sandbox_id}/files/{file_id}")
def conversation_execution_artifact(conversation_id: str, message_id: str, sandbox_id: str, file_id: str,
                                    service: ConversationStoreDependency, inline: bool = False):
    conversation = service.get(conversation_id)
    if conversation is None or not any(item.message_id == message_id and item.role == "assistant" for item in conversation.messages):
        raise HTTPException(status_code=404, detail="Assistant message not found in this conversation.")
    receipt = next((r for r in load_execution_results(service.storage_path, message_id) if r.sandbox_id == sandbox_id), None)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Execution not found in this message.")
    from backend.sandbox.workspace import SandboxWorkspaceManager
    try:
        filename, data = read_manifest_artifact(sandbox_id, receipt.output_files, file_id, SandboxWorkspaceManager().artifact_root)
        if inline:
            from backend.services.execution_image_service import image_response
            return image_response(filename, data)
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "X-Content-Type-Options": "nosniff"})
    except SandboxDebugError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{conversation_id}/export/markdown", response_model=MarkdownDocument)
def export_conversation_markdown(
    conversation_id: str,
    service: ConversationStoreDependency,
    message_id: str = Query(default="", max_length=128),
) -> MarkdownDocument:
    conversation = service.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    try:
        if not message_id:
            return conversation_markdown(conversation.title, conversation.messages)
        message = next((item for item in conversation.messages if item.message_id == message_id), None)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found in this conversation.")
        if message.role != "assistant" or message.status != "complete":
            raise HTTPException(status_code=409, detail="只能导出已完成的回答。")
        return load_markdown_export(service.storage_path, message_id) or markdown_document(message.content, conversation.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{conversation_id}", response_model=ConversationDetailResponse)
def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    service: ConversationStoreDependency,
) -> ConversationDetailResponse:
    try:
        conversation = service.rename(conversation_id, payload.title)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return _detail_response(service, conversation)


@router.post(
    "/{conversation_id}/rewind",
    response_model=ConversationDetailResponse,
)
def rewind_conversation(
    conversation_id: str,
    payload: ConversationRewindRequest,
    service: ConversationStoreDependency,
    ownership: CompanionOwnershipDependency,
) -> ConversationDetailResponse:
    _assert_conversation_idle(ownership, conversation_id)
    rewind = getattr(service, "rewind_from_user_message", None)
    if not callable(rewind):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Conversation branch rewriting is unavailable.",
        )
    try:
        conversation = rewind(conversation_id, payload.user_message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation or user message not found.",
        )
    return _detail_response(service, conversation)


@router.patch(
    "/{conversation_id}/context",
    response_model=ConversationDetailResponse,
)
def update_conversation_context(
    conversation_id: str,
    payload: ConversationContextUpdateRequest,
    service: ConversationStoreDependency,
    ownership: CompanionOwnershipDependency,
) -> ConversationDetailResponse:
    _assert_conversation_idle(ownership, conversation_id)
    update_context = getattr(service, "update_context", None)
    if not callable(update_context):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Conversation context management is unavailable.",
        )
    fields = payload.model_dump(exclude_none=True)
    mode = str(fields.pop("context_mode"))
    try:
        conversation = update_context(
            conversation_id,
            context_mode=mode,
            **fields,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return _detail_response(service, conversation)


@router.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
def delete_conversation(
    conversation_id: str,
    service: ConversationStoreDependency,
    ownership: CompanionOwnershipDependency,
) -> ConversationDeleteResponse:
    _assert_conversation_idle(ownership, conversation_id)
    return ConversationDeleteResponse(
        deleted=service.delete(conversation_id),
        conversation_id=conversation_id,
    )
