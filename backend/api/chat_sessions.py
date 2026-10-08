from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import get_filesystem_workspace_service
from backend.services.chat_session_service import (
    ChatSessionConfiguration,
    ChatSessionService,
)

router = APIRouter(prefix="/api/companion/sessions", tags=["chat-sessions"])


@lru_cache(maxsize=1)
def get_chat_session_service() -> ChatSessionService:
    return ChatSessionService(get_filesystem_workspace_service())


Service = Annotated[ChatSessionService, Depends(get_chat_session_service)]


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filesystem_workspace_id: str | None = Field(default=None, max_length=128)
    execution_mode: Literal["react", "plan_execute"] | None = None


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@router.get("/{session_id}", response_model=ChatSessionConfiguration)
def get_configuration(session_id: str, service: Service):
    return service.get(session_id)


@router.patch("/{session_id}", response_model=ChatSessionConfiguration)
def update_configuration(
    session_id: str, payload: ConfigurationUpdate, service: Service
):
    try:
        return service.update(session_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{session_id}/files", response_model=ChatSessionConfiguration)
def import_file(session_id: str, payload: ImportRequest, service: Service):
    try:
        return service.import_file(session_id, payload.path)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete(
    "/{session_id}/files/{attachment_id}", response_model=ChatSessionConfiguration
)
def detach_file(session_id: str, attachment_id: str, service: Service):
    try:
        return service.detach(session_id, attachment_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
