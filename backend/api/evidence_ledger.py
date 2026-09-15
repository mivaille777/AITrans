from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.evidence_ledger_dependencies import get_evidence_ledger_service
from backend.models.evidence_ledger import EvidenceLedgerItem, EvidenceLedgerSnapshot
from backend.services.evidence_ledger_service import EvidenceLedgerService

router = APIRouter(prefix="/api/research", tags=["evidence-ledger"])
EvidenceLedgerDependency = Annotated[
    EvidenceLedgerService,
    Depends(get_evidence_ledger_service),
]


def _raise_ledger_error(exc: Exception) -> None:
    message = str(exc) or "Invalid Evidence Ledger request."
    code = (
        status.HTTP_404_NOT_FOUND
        if "not found" in message.casefold()
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(status_code=code, detail=message) from exc


@router.get(
    "/workspaces/{workspace_id}/evidence-ledger",
    response_model=EvidenceLedgerSnapshot,
)
def get_evidence_ledger(
    workspace_id: str,
    service: EvidenceLedgerDependency,
    q: str = Query(default="", max_length=4_000),
    limit: int = Query(default=100, ge=1, le=500),
) -> EvidenceLedgerSnapshot:
    """Return persisted research claims after live provenance revalidation."""

    try:
        return service.snapshot(
            workspace_id=workspace_id,
            query=q,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_ledger_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/workspaces/{workspace_id}/evidence-ledger/{entry_id}",
    response_model=EvidenceLedgerItem,
)
def get_evidence_ledger_entry(
    workspace_id: str,
    entry_id: str,
    service: EvidenceLedgerDependency,
) -> EvidenceLedgerItem:
    """Return one ledger Claim with its current validation state."""

    try:
        item = service.get(workspace_id=workspace_id, entry_id=entry_id)
    except Exception as exc:  # noqa: BLE001 - translated to local API contract
        _raise_ledger_error(exc)
        raise AssertionError("unreachable")
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence Ledger entry not found.",
        )
    return item


__all__ = ["router"]
