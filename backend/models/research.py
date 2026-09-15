from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ResearchSourceFamily = Literal["browser", "pdf", "word", "desktop", "other"]
ResearchIdentityQuality = Literal["locator", "title", "note"]
ResearchWorkspaceMemberKind = Literal["document", "note", "conversation"]


class ResearchSourceSummaryResponse(BaseModel):
    source_id: str
    display_title: str
    resource_url: str = ""
    resource_locator: str = ""
    source_kind: str = ""
    source_family: ResearchSourceFamily = "other"
    identity_quality: ResearchIdentityQuality = "note"
    note_count: int = 0
    section_count: int = 0
    linked_conversation_count: int = 0
    annotation_count: int = 0
    ai_evidence_count: int = 0
    updated_at: str = ""


class ResearchSourceSectionResponse(BaseModel):
    section_id: str
    heading: str
    note_count: int = 0
    linked_conversation_count: int = 0
    annotation_count: int = 0
    ai_evidence_count: int = 0
    updated_at: str = ""


class ResearchSourceProfileResponse(ResearchSourceSummaryResponse):
    sections: list[ResearchSourceSectionResponse]


class ResearchNoteDetailResponse(BaseModel):
    note_id: str
    source_id: str
    created_at: str
    updated_at: str
    display_title: str
    excerpt: str
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
    user_note: str = ""
    conversation_id: str = ""


class ResearchNoteSearchResultResponse(BaseModel):
    note_id: str
    source_id: str
    display_title: str
    excerpt: str
    resource_url: str = ""
    resource_title: str = ""
    section_heading: str = ""
    source_kind: str = ""
    user_note: str = ""
    score: float = Field(ge=0.0)


class ResearchNoteSearchResponse(BaseModel):
    query: str
    count: int = Field(ge=0)
    results: list[ResearchNoteSearchResultResponse] = Field(default_factory=list)


# Legacy aggregate research-memory response retained for the existing
# /api/research/workspace endpoint. Stage 16 project workspaces use the
# ResearchWorkspace* contracts below.
class ResearchWorkspaceResponse(BaseModel):
    total: int
    sources: list[ResearchSourceSummaryResponse]
    notes: list[ResearchNoteDetailResponse]


class ResearchWorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)
    research_goal: str = Field(default="", max_length=8_000)


class ResearchWorkspaceUpdateRequest(ResearchWorkspaceCreateRequest):
    pass


class ResearchWorkspaceMemberRequest(BaseModel):
    resource_id: str = Field(min_length=1, max_length=256)


class ResearchWorkspaceSummaryResponse(BaseModel):
    workspace_id: str
    name: str
    description: str = ""
    research_goal: str = ""
    created_at: str
    updated_at: str
    document_count: int = Field(default=0, ge=0)
    note_count: int = Field(default=0, ge=0)
    conversation_count: int = Field(default=0, ge=0)


class ResearchWorkspaceProfileResponse(ResearchWorkspaceSummaryResponse):
    document_ids: list[str] = Field(default_factory=list)
    note_ids: list[str] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)


class ResearchWorkspaceListResponse(BaseModel):
    total: int = Field(ge=0)
    workspaces: list[ResearchWorkspaceSummaryResponse] = Field(default_factory=list)


class ResearchWorkspaceDeleteResponse(BaseModel):
    deleted: bool
    workspace_id: str
    resources_preserved: bool = True


class ResearchWorkspaceMemberResponse(BaseModel):
    workspace_id: str
    kind: ResearchWorkspaceMemberKind
    resource_id: str
    attached: bool


class ResearchNoteUpdateRequest(BaseModel):
    user_note: str = Field(default="", max_length=20_000)


class ResearchNoteDeleteResponse(BaseModel):
    deleted: bool
    note_id: str
