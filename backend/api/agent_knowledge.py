from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.agent_knowledge_runtime import AgentKnowledgeRuntime

router = APIRouter(prefix="/api/agent/knowledge", tags=["agent-knowledge"])

runtime = AgentKnowledgeRuntime()


class AgentKnowledgeContextRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/context")
def build_agent_context(payload: AgentKnowledgeContextRequest):
    result = runtime.build_context(payload.query, payload.top_k)
    return {
        "query": result.query,
        "context": result.context,
        "citations": result.citations,
    }


__all__ = ["router"]
