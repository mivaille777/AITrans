from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.agent_core.supervisor import SupervisorKnowledgeRouter

router = APIRouter(prefix="/api/agent/routing", tags=["agent-routing"])
_router = SupervisorKnowledgeRouter()


class RouteRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=4000)


@router.post("/decision")
def routing_decision(payload: RouteRequest):
    class State:
        user_input = payload.user_input

    decision = _router.decide(State())
    return {
        "need_knowledge": decision.need_knowledge,
        "reason": decision.reason,
        "tool_name": decision.tool_name,
    }


__all__ = ["router"]
