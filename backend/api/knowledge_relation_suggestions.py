from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.errors import AIConfigurationError, AIError
from backend.api.knowledge_relation_suggestion_dependencies import (
    get_knowledge_relation_suggestion_service,
)
from backend.knowledge.domain import KnowledgeRelationSuggestionStatus
from backend.models.knowledge_relation_suggestion_api import (
    KnowledgeRelationSuggestionDecisionResponse,
    KnowledgeRelationSuggestionGenerateRequest,
    KnowledgeRelationSuggestionListResponse,
)
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)

router = APIRouter(
    prefix="/api/knowledge/relation-suggestions",
    tags=["knowledge"],
)
SuggestionServiceDependency = Annotated[
    KnowledgeRelationSuggestionService,
    Depends(get_knowledge_relation_suggestion_service),
]


@router.get("", response_model=KnowledgeRelationSuggestionListResponse)
def list_relation_suggestions(
    service: SuggestionServiceDependency,
    focus_item_id: str | None = None,
    status_filter: Annotated[
        KnowledgeRelationSuggestionStatus | None,
        Query(alias="status"),
    ] = None,
) -> KnowledgeRelationSuggestionListResponse:
    suggestions = service.list(
        focus_item_id=focus_item_id,
        status=status_filter,
    )
    return KnowledgeRelationSuggestionListResponse(
        total=len(suggestions),
        suggestions=suggestions,
    )


@router.post(
    "/generate",
    response_model=KnowledgeRelationSuggestionListResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_relation_suggestions(
    payload: KnowledgeRelationSuggestionGenerateRequest,
    service: SuggestionServiceDependency,
) -> KnowledgeRelationSuggestionListResponse:
    try:
        suggestions = service.generate(
            focus_item_id=payload.focus_item_id,
            candidate_item_ids=payload.candidate_item_ids,
            max_suggestions=payload.max_suggestions,
        )
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeRelationSuggestionListResponse(
        total=len(suggestions),
        suggestions=suggestions,
    )


@router.post(
    "/{suggestion_id}/accept",
    response_model=KnowledgeRelationSuggestionDecisionResponse,
)
def accept_relation_suggestion(
    suggestion_id: str,
    service: SuggestionServiceDependency,
) -> KnowledgeRelationSuggestionDecisionResponse:
    try:
        suggestion, relation = service.accept(suggestion_id)
    except ValueError as exc:
        message = str(exc)
        code = 404 if "does not exist" in message else 422
        raise HTTPException(status_code=code, detail=message) from exc
    return KnowledgeRelationSuggestionDecisionResponse(
        suggestion=suggestion,
        relation=relation,
    )


@router.post(
    "/{suggestion_id}/reject",
    response_model=KnowledgeRelationSuggestionDecisionResponse,
)
def reject_relation_suggestion(
    suggestion_id: str,
    service: SuggestionServiceDependency,
) -> KnowledgeRelationSuggestionDecisionResponse:
    try:
        suggestion = service.reject(suggestion_id)
    except ValueError as exc:
        message = str(exc)
        code = 404 if "does not exist" in message else 422
        raise HTTPException(status_code=code, detail=message) from exc
    return KnowledgeRelationSuggestionDecisionResponse(suggestion=suggestion)


__all__ = ["router"]
