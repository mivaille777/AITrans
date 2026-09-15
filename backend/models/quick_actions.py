from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

QuickActionKey = Literal[
    "ai_polish",
    "reading_context_translate",
    "reading_explain",
    "reading_summarize",
    "reading_section_role",
]


class ReadingContextPayload(BaseModel):
    source_text: str = Field(min_length=1, max_length=20_000)
    translated_text: str = Field(default="", max_length=50_000)
    source_language: str = "auto"
    target_language: str = "zh-CN"
    resource_url: str = Field(default="", max_length=4096)
    resource_title: str = Field(default="", max_length=1024)
    section_heading: str = Field(default="", max_length=1024)
    context_before: str = Field(default="", max_length=4000)
    context_after: str = Field(default="", max_length=4000)
    source_kind: str = Field(default="browser_selection", max_length=128)

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("language code must not be empty")
        return normalized


class QuickActionRequest(ReadingContextPayload):
    action: QuickActionKey
    style: str = Field(default="academic", min_length=1, max_length=64)
    request_id: int = Field(default=0, ge=0)


class QuickActionResponse(BaseModel):
    action: QuickActionKey
    output_text: str
    provider: str
    model: str
    request_id: int


class QuickActionStatusResponse(BaseModel):
    available: bool
    provider: str = ""
    model: str = ""
    detail: str = ""


class ResearchNoteSaveRequest(ReadingContextPayload):
    ai_content: str = Field(default="", max_length=30_000)
    ai_action: str = Field(default="", max_length=128)
    user_note: str = Field(default="", max_length=20_000)
    conversation_id: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)


class ResearchNoteSaveResponse(BaseModel):
    note_id: str
    created: bool
    display_title: str
    excerpt: str
    updated_at: str
    conversation_id: str = ""


class ResearchNoteListItem(BaseModel):
    note_id: str
    display_title: str
    excerpt: str
    updated_at: str
    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    source_text: str = ""
    translated_text: str = ""
    context_before: str = ""
    context_after: str = ""
    source_kind: str = ""
    ai_content: str = ""
    ai_action: str = ""
    conversation_id: str = ""


class ResearchNoteListResponse(BaseModel):
    total: int
    notes: list[ResearchNoteListItem]
