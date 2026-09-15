from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.evidence_review_dependencies import (
    get_agent_literature_synthesis_service,
    get_evidence_review_service,
)
from backend.models.evidence_review import (
    AgentLiteratureSynthesisResponse,
    EvidenceReviewSnapshot,
    EvidenceReviewUpdateRequest,
    LiteratureSynthesisPlan,
    LiteratureSynthesisRequest,
    ReviewedEvidenceLedgerItem,
)
from backend.services.agent_literature_synthesis_service import AgentLiteratureSynthesisService
from backend.services.evidence_review_service import EvidenceReviewService

router = APIRouter(prefix="/api/research", tags=["evidence-review"])
EvidenceReviewDependency = Annotated[EvidenceReviewService, Depends(get_evidence_review_service)]
AgentLiteratureSynthesisDependency = Annotated[
    AgentLiteratureSynthesisService,
    Depends(get_agent_literature_synthesis_service),
]


def _raise_review_error(exc: Exception) -> None:
    message = str(exc) or "Invalid Evidence Review request."
    code = status.HTTP_404_NOT_FOUND if "not found" in message.casefold() else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=code, detail=message) from exc


@router.get("/workspaces/{workspace_id}/evidence-review", response_model=EvidenceReviewSnapshot)
def get_evidence_review(
    workspace_id: str,
    service: EvidenceReviewDependency,
    q: str = Query(default="", max_length=4000),
    limit: int = Query(default=100, ge=1, le=500),
) -> EvidenceReviewSnapshot:
    try:
        return service.snapshot(workspace_id=workspace_id, query=q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _raise_review_error(exc)
        raise AssertionError("unreachable")


@router.patch(
    "/workspaces/{workspace_id}/evidence-review/{entry_id}",
    response_model=ReviewedEvidenceLedgerItem,
)
def review_evidence_entry(
    workspace_id: str,
    entry_id: str,
    payload: EvidenceReviewUpdateRequest,
    service: EvidenceReviewDependency,
) -> ReviewedEvidenceLedgerItem:
    try:
        return service.review(
            workspace_id=workspace_id,
            entry_id=entry_id,
            status=payload.status,
            note=payload.note,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_review_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/workspaces/{workspace_id}/literature-synthesis",
    response_model=LiteratureSynthesisPlan,
)
def synthesize_literature(
    workspace_id: str,
    payload: LiteratureSynthesisRequest,
    service: EvidenceReviewDependency,
) -> LiteratureSynthesisPlan:
    try:
        return service.synthesize(workspace_id=workspace_id, query=payload.query)
    except Exception as exc:  # noqa: BLE001
        _raise_review_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/workspaces/{workspace_id}/literature-synthesis/agent",
    response_model=AgentLiteratureSynthesisResponse,
)
def synthesize_literature_with_agent(
    workspace_id: str,
    payload: LiteratureSynthesisRequest,
    service: AgentLiteratureSynthesisDependency,
) -> AgentLiteratureSynthesisResponse:
    """Generate a verified natural-language synthesis from Review Gate evidence only."""

    try:
        return service.generate(workspace_id=workspace_id, query=payload.query)
    except Exception as exc:  # noqa: BLE001 - provider errors already degrade in service
        _raise_review_error(exc)
        raise AssertionError("unreachable")


__all__ = ["router"]
