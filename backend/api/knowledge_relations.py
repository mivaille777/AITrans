from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.knowledge_workspace_dependencies import get_knowledge_workspace_service
from backend.knowledge.domain import KnowledgeRelation
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.models.knowledge_relation_api import (
    KnowledgeRelationCreateRequest,
    KnowledgeRelationDeleteResponse,
    KnowledgeRelationListResponse,
    KnowledgeRelationUpdateRequest,
)

router = APIRouter(prefix="/api/knowledge/relations", tags=["knowledge"])
WorkspaceDependency = Annotated[
    KnowledgeWorkspaceService,
    Depends(get_knowledge_workspace_service),
]


def _relation_or_404(
    relation_id: str,
    workspace: KnowledgeWorkspaceService,
) -> KnowledgeRelation:
    relation = workspace.get_relation(relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="Knowledge relation not found.")
    return relation


@router.get("", response_model=KnowledgeRelationListResponse)
def list_knowledge_relations(
    workspace: WorkspaceDependency,
    item_id: str | None = None,
) -> KnowledgeRelationListResponse:
    relations = workspace.list_relations(item_id=item_id)
    return KnowledgeRelationListResponse(total=len(relations), relations=relations)


@router.get("/{relation_id}", response_model=KnowledgeRelation)
def get_knowledge_relation(
    relation_id: str,
    workspace: WorkspaceDependency,
) -> KnowledgeRelation:
    return _relation_or_404(relation_id, workspace)


@router.post("", response_model=KnowledgeRelation, status_code=status.HTTP_201_CREATED)
def create_knowledge_relation(
    payload: KnowledgeRelationCreateRequest,
    workspace: WorkspaceDependency,
) -> KnowledgeRelation:
    try:
        return workspace.create_relation(
            source_item_id=payload.source_item_id,
            target_item_id=payload.target_item_id,
            relation_type=payload.relation_type,
            label=payload.label,
            origin=payload.origin,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{relation_id}", response_model=KnowledgeRelation)
def update_knowledge_relation(
    relation_id: str,
    payload: KnowledgeRelationUpdateRequest,
    workspace: WorkspaceDependency,
) -> KnowledgeRelation:
    _relation_or_404(relation_id, workspace)
    update_kwargs = {
        "relation_type": payload.relation_type,
        "label": payload.label,
    }
    if "confidence" in payload.model_fields_set:
        update_kwargs["confidence"] = payload.confidence
    try:
        updated = workspace.update_relation(
            relation_id,
            **update_kwargs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Knowledge relation not found.")
    return updated


@router.delete("/{relation_id}", response_model=KnowledgeRelationDeleteResponse)
def delete_knowledge_relation(
    relation_id: str,
    workspace: WorkspaceDependency,
) -> KnowledgeRelationDeleteResponse:
    _relation_or_404(relation_id, workspace)
    return KnowledgeRelationDeleteResponse(
        relation_id=relation_id,
        deleted=workspace.delete_relation(relation_id),
    )


__all__ = ["router"]
