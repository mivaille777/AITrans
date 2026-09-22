from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
)
from backend.models.quick_actions import ReadingContextPayload


class CompanionHandoffRequest(ReadingContextPayload):
    conversation_id: str = Field(default="", max_length=128)
    ai_content: str = Field(default="", max_length=30_000)
    ai_action: str = Field(default="", max_length=128)
    suggested_prompt: str = Field(default="", max_length=2_000)
    knowledge_enabled: bool = False
    knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)


class CompanionHandoffResponse(ReadingContextPayload):
    revision: int
    handoff_id: str
    created_at: str
    conversation_id: str = ""
    ai_content: str = ""
    ai_action: str = ""
    suggested_prompt: str = ""
    knowledge_enabled: bool = False
    knowledge_document_ids: list[str] = Field(default_factory=list)


class CompanionHandoffEnvelope(BaseModel):
    handoff: CompanionHandoffResponse | None = None


class CompanionDismissRequest(BaseModel):
    handoff_id: str = Field(default="", max_length=128)


CompanionChatRole = Literal["user", "assistant"]
CompanionChatContextMode = Literal["general", "reading"]
CompanionClientSurface = Literal["main", "overlay", "unknown"]


class CompanionChatMessage(BaseModel):
    role: CompanionChatRole
    content: str = Field(min_length=1, max_length=30_000)


class CompanionChatRequest(BaseModel):
    conversation_id: str = Field(default="", max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(default="", max_length=128)
    client_surface: CompanionClientSurface = "unknown"
    user_message: str = Field(min_length=1, max_length=20_000)
    history: list[CompanionChatMessage] = Field(default_factory=list, max_length=32)
    request_id: int = Field(default=0, ge=0)
    context_mode: CompanionChatContextMode = "reading"
    source_text: str = Field(default="", max_length=20_000)
    translated_text: str = Field(default="", max_length=50_000)
    source_language: str = Field(default="auto", max_length=64)
    target_language: str = Field(default="zh-CN", max_length=64)
    resource_url: str = Field(default="", max_length=4096)
    resource_title: str = Field(default="", max_length=1024)
    section_heading: str = Field(default="", max_length=1024)
    context_before: str = Field(default="", max_length=4000)
    context_after: str = Field(default="", max_length=4000)
    source_kind: str = Field(default="", max_length=128)
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_enabled: bool | None = None
    knowledge_document_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("language code must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_reading_context(self) -> CompanionChatRequest:
        if self.context_mode == "reading" and not self.source_text.strip():
            raise ValueError("Reading-grounded chat requires selected source text.")
        if (
            self.knowledge_enabled is not None
            and "knowledge_access_policy" not in self.model_fields_set
        ):
            # Keep older desktop clients working while ensuring new clients can
            # explicitly send Auto without the legacy boolean overriding it.
            self.knowledge_access_policy = (
                KnowledgeAccessPolicy.ALWAYS
                if self.knowledge_enabled
                else KnowledgeAccessPolicy.NEVER
            )
        return self


class CompanionChatResponse(BaseModel):
    conversation_id: str = ""
    session_id: str
    user_message: str
    output_text: str
    provider: str
    model: str
    request_id: int
    knowledge_enabled: bool = False
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_decision: KnowledgeAccessDecision | None = None
    knowledge_retrieved: bool = False
    knowledge_document_count: int = Field(default=0, ge=0)
    knowledge_chunk_count: int = Field(default=0, ge=0)
    knowledge_fallback_reason: str = ""
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)


class CompanionChatStatusResponse(BaseModel):
    available: bool
    provider: str = ""
    model: str = ""
    detail: str = ""


class CompanionChatOwnershipResponse(BaseModel):
    conversation_id: str
    busy: bool
    owner_id: str = ""
    owner_surface: CompanionClientSurface = "unknown"
    request_id: int = 0
    stale_after_seconds: float = 0.0


class CompanionChatStreamStart(BaseModel):
    type: Literal["start"]
    request: CompanionChatRequest


class CompanionChatStreamCancel(BaseModel):
    type: Literal["cancel"]
    request_id: int = Field(ge=0)
