from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem

ConversationMessageStatus = Literal["complete", "streaming", "cancelled", "error"]
ConversationRole = Literal["user", "assistant"]
ConversationContextMode = Literal["general", "reading"]


class ConversationMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    request_id: int
    role: ConversationRole
    content: str
    status: ConversationMessageStatus
    provider: str = ""
    model: str = ""
    error_code: str = ""
    knowledge_enabled: bool = False
    knowledge_fallback_reason: str = ""
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ConversationSummaryResponse(BaseModel):
    conversation_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str
    provider: str = ""
    model: str = ""
    context_mode: ConversationContextMode = "reading"
    resource_title: str = ""
    section_heading: str = ""
    source_kind: str = ""


class ConversationDetailResponse(ConversationSummaryResponse):
    source_text: str = ""
    translated_text: str = ""
    source_language: str = "auto"
    target_language: str = "zh-CN"
    resource_url: str = ""
    context_before: str = ""
    context_after: str = ""
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummaryResponse]


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationRewindRequest(BaseModel):
    user_message_id: str = Field(min_length=1, max_length=128)


class ConversationContextUpdateRequest(BaseModel):
    context_mode: ConversationContextMode
    source_text: str | None = Field(default=None, max_length=20_000)
    translated_text: str | None = Field(default=None, max_length=50_000)
    source_language: str | None = Field(default=None, max_length=64)
    target_language: str | None = Field(default=None, max_length=64)
    resource_url: str | None = Field(default=None, max_length=4096)
    resource_title: str | None = Field(default=None, max_length=1024)
    section_heading: str | None = Field(default=None, max_length=1024)
    context_before: str | None = Field(default=None, max_length=4000)
    context_after: str | None = Field(default=None, max_length=4000)
    source_kind: str | None = Field(default=None, max_length=128)


class ConversationDeleteResponse(BaseModel):
    deleted: bool
    conversation_id: str
