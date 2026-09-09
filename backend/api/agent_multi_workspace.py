from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from backend.models.multi_agent_workspace import (
    MultiAgentContextSnapshot,
    MultiAgentPlanStep,
    MultiAgentResultResponse,
    MultiAgentRunRequest,
    MultiAgentRunTraceResponse,
    MultiAgentTraceEventResponse,
)
from backend.services.multi_agent_workspace_service import MultiAgentWorkspaceService


router = APIRouter(prefix="/api/agent/multi-agent", tags=["agent-multi-workspace"])
_service = MultiAgentWorkspaceService()


@router.post("/run/trace", response_model=MultiAgentRunTraceResponse)
def run_multi_agent_trace(payload: MultiAgentRunRequest) -> MultiAgentRunTraceResponse:
    try:
        run = _service.run(
            payload.task,
            user_id=payload.user_id.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return MultiAgentRunTraceResponse(
        run_id=run.run_id,
        trace_id=run.trace_id,
        total_duration_ms=run.total_duration_ms,
        plan=[
            MultiAgentPlanStep(agent=str(item.get("agent") or ""))
            for item in run.plan
        ],
        results=[
            MultiAgentResultResponse(
                agent_name=result.agent_name,
                output=result.output,
                metadata=dict(result.metadata or {}),
            )
            for result in run.results
        ],
        context=MultiAgentContextSnapshot(
            knowledge_context_chars=len(run.context.knowledge_context or ""),
            citation_count=len(run.context.citations),
            citations=[dict(item) for item in run.context.citations[:20]],
            memory_keys=sorted(str(key) for key in run.context.memory.keys()),
            intermediate_agents=sorted(run.context.intermediate_results.keys()),
        ),
        events=[
            MultiAgentTraceEventResponse(**asdict(event))
            for event in run.events
        ],
    )


__all__ = ["router"]
