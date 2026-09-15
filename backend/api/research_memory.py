from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.ai.errors import AIConfigurationError, AIError
from app.research.memory import ResearchMemorySnapshot
from backend.api.research_memory_dependencies import get_research_memory_service
from backend.models.research_memory import (
    ResearchMemoryClaimResponse,
    ResearchMemoryEntityResponse,
    ResearchMemoryEvidenceResponse,
    ResearchMemoryExtractionResponse,
    ResearchMemoryRelationResponse,
    ResearchMemorySearchResponse,
    ResearchMemoryWorkspaceResponse,
)
from backend.services.research_memory_service import ResearchMemoryService

router = APIRouter(prefix="/api/research", tags=["research-memory"])
ResearchMemoryDependency = Annotated[
    ResearchMemoryService,
    Depends(get_research_memory_service),
]


def _workspace_response(
    workspace_id: str,
    snapshot: ResearchMemorySnapshot,
) -> ResearchMemoryWorkspaceResponse:
    return ResearchMemoryWorkspaceResponse(
        workspace_id=workspace_id,
        extraction_count=len(snapshot.extractions),
        claims=[
            ResearchMemoryClaimResponse(
                claim_id=item.claim_id,
                note_id=item.note_id,
                claim_type=item.claim_type,
                text=item.text,
                confidence=item.confidence,
                created_at=item.created_at,
            )
            for item in snapshot.claims
        ],
        evidence=[
            ResearchMemoryEvidenceResponse(
                evidence_id=item.evidence_id,
                claim_id=item.claim_id,
                note_id=item.note_id,
                excerpt=item.excerpt,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                source_verified=item.start_offset >= 0 and item.end_offset >= item.start_offset,
                created_at=item.created_at,
            )
            for item in snapshot.evidence
        ],
        entities=[
            ResearchMemoryEntityResponse(
                entity_id=item.entity_id,
                canonical_name=item.canonical_name,
                entity_type=item.entity_type,
                aliases=list(item.aliases),
                description=item.description,
                updated_at=item.updated_at,
            )
            for item in snapshot.entities
        ],
        relations=[
            ResearchMemoryRelationResponse(
                relation_id=item.relation_id,
                note_id=item.note_id,
                subject_entity_id=item.source_entity_id,
                predicate=item.predicate,
                object_entity_id=item.target_entity_id,
                claim_id=item.claim_id,
                confidence=item.confidence,
                created_at=item.created_at,
            )
            for item in snapshot.relations
        ],
    )


def _raise_memory_error(exc: Exception) -> None:
    if isinstance(exc, AIConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if isinstance(exc, AIError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    message = str(exc) or "Invalid structured research-memory request."
    code = status.HTTP_404_NOT_FOUND if "not found" in message.casefold() else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=code, detail=message) from exc


@router.post(
    "/workspaces/{workspace_id}/memory/notes/{note_id}/extract",
    response_model=ResearchMemoryExtractionResponse,
)
def extract_research_memory_note(
    workspace_id: str,
    note_id: str,
    service: ResearchMemoryDependency,
) -> ResearchMemoryExtractionResponse:
    try:
        record = service.extract_note(workspace_id=workspace_id, note_id=note_id)
        snapshot = service.snapshot(workspace_id=workspace_id, limit=500)
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_memory_error(exc)
        raise AssertionError("unreachable")

    return ResearchMemoryExtractionResponse(
        extraction_id=record.extraction_id,
        workspace_id=record.workspace_id,
        note_id=record.note_id,
        extractor_version=record.extractor_version,
        prompt_id=record.prompt_id,
        claim_count=sum(1 for item in snapshot.claims if item.note_id == note_id),
        evidence_count=sum(1 for item in snapshot.evidence if item.note_id == note_id),
        entity_count=len(snapshot.entities),
        relation_count=sum(1 for item in snapshot.relations if item.note_id == note_id),
        updated_at=record.updated_at,
    )


@router.get(
    "/workspaces/{workspace_id}/memory",
    response_model=ResearchMemoryWorkspaceResponse,
)
def get_research_memory_workspace(
    workspace_id: str,
    service: ResearchMemoryDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> ResearchMemoryWorkspaceResponse:
    try:
        snapshot = service.snapshot(workspace_id=workspace_id, limit=limit)
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_memory_error(exc)
        raise AssertionError("unreachable")
    return _workspace_response(workspace_id, snapshot)


@router.get(
    "/workspaces/{workspace_id}/memory/search",
    response_model=ResearchMemorySearchResponse,
)
def search_research_memory_workspace(
    workspace_id: str,
    service: ResearchMemoryDependency,
    q: str = Query(min_length=1, max_length=4_000),
    limit: int = Query(default=12, ge=1, le=50),
) -> ResearchMemorySearchResponse:
    try:
        results = service.search(
            workspace_id=workspace_id,
            query=q,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_memory_error(exc)
        raise AssertionError("unreachable")
    return ResearchMemorySearchResponse(
        workspace_id=workspace_id,
        query=q,
        count=len(results),
        results=list(results),
    )


@router.delete("/workspaces/{workspace_id}/memory/notes/{note_id}")
def delete_research_memory_note(
    workspace_id: str,
    note_id: str,
    service: ResearchMemoryDependency,
) -> dict[str, object]:
    try:
        deleted = service.delete_note_memory(
            workspace_id=workspace_id,
            note_id=note_id,
        )
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_memory_error(exc)
        raise AssertionError("unreachable")
    return {
        "workspace_id": workspace_id,
        "note_id": note_id,
        "deleted": deleted,
        "research_note_preserved": True,
    }


__all__ = ["router"]
