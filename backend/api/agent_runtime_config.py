from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.chat.service import CHAT_PROMPT, DEFAULT_CHAT_CONTEXT_MAX_CHARS
from app.ai.gateway import LLMGateway
from app.ai.prompts import POLISH_PROMPT, STRICT_RETRY_PROMPT, TRANSLATE_PROMPT
from backend.api.llm_dependencies import get_llm_gateway
from backend.models.agent_runtime_config import (
    AgentModelRouteInfo,
    AgentPromptInfo,
    AgentRuntimeConfigResponse,
)
from backend.rag.query_planner import RAG_QUERY_PLANNER_PROMPT
from backend.services.agent_multi_step_planner_service import MULTI_STEP_PLANNER_PROMPT
from backend.services.agent_planner_service import (
    AGENT_PLANNER_CONTEXT_MAX_CHARS,
    AGENT_PLANNER_PROMPT,
)

router = APIRouter(prefix="/api/agent", tags=["agent-runtime"])
LLMGatewayDependency = Annotated[LLMGateway, Depends(get_llm_gateway)]


@router.get("/runtime/config", response_model=AgentRuntimeConfigResponse)
def get_agent_runtime_config(
    gateway: LLMGatewayDependency,
) -> AgentRuntimeConfigResponse:
    prompts = (
        AGENT_PLANNER_PROMPT,
        MULTI_STEP_PLANNER_PROMPT,
        RAG_QUERY_PLANNER_PROMPT,
        CHAT_PROMPT,
        TRANSLATE_PROMPT,
        POLISH_PROMPT,
        STRICT_RETRY_PROMPT,
    )
    return AgentRuntimeConfigResponse(
        model_routes=[
            AgentModelRouteInfo(
                role=route.role,
                provider=route.provider,
                model=route.model,
                thinking_enabled=route.thinking_enabled,
            )
            for route in gateway.describe_routes()
        ],
        prompts=[
            AgentPromptInfo(
                name=prompt.name,
                version=prompt.version,
                prompt_id=prompt.prompt_id,
            )
            for prompt in prompts
        ],
        planner_context_max_chars=AGENT_PLANNER_CONTEXT_MAX_CHARS,
        chat_context_max_chars=DEFAULT_CHAT_CONTEXT_MAX_CHARS,
    )


__all__ = ["router"]
