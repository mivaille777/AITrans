from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.knowledge_v2_dependencies import get_knowledge_v2_service
from backend.knowledge.v2_service import KnowledgeV2Service

router = APIRouter(prefix="/api/knowledge/v2", tags=["knowledge-v2"])


@router.get("/cards")
def list_cards(service: KnowledgeV2Service = Depends(get_knowledge_v2_service)):
    return service.list_cards()


@router.get("/cards/{card_id}")
def get_card(
    card_id: str,
    service: KnowledgeV2Service = Depends(get_knowledge_v2_service),
):
    card = service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    return card


@router.get("/graph")
def get_graph(service: KnowledgeV2Service = Depends(get_knowledge_v2_service)):
    return service.get_graph()


@router.get("/events")
def list_events(service: KnowledgeV2Service = Depends(get_knowledge_v2_service)):
    return service.list_agent_events()
