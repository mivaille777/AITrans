from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/knowledge/v2", tags=["knowledge-v2"])


# The dependency wiring is intentionally separated from this router. The
# existing application factory can inject KnowledgeV2Service without changing
# current KnowledgeWorkspaceService routes.
def _service(request: Any):
    service = getattr(request.app.state, "knowledge_v2_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Knowledge 2.0 service is not initialized",
        )
    return service


@router.get("/cards")
def list_cards(request: Any):
    return _service(request).list_cards()


@router.get("/cards/{card_id}")
def get_card(card_id: str, request: Any):
    card = _service(request).get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    return card


@router.get("/graph")
def get_graph(request: Any):
    return _service(request).get_graph()


@router.get("/events")
def list_events(request: Any):
    return _service(request).list_agent_events()
