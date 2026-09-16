from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.models.agent_artifacts import ArtifactRef, ReferenceRecord


class WritingProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WritingProjectCreateRequest(WritingProjectModel):
    workspace_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=1000)
    writing_goal: str = Field(default="", max_length=20_000)


class WritingArtifactSaveRequest(WritingProjectModel):
    artifact_id: str = Field(min_length=1, max_length=256)
    artifact_version: int = Field(ge=1)
    expected_version: int = Field(default=0, ge=0)


class WritingRevisionApplyRequest(WritingArtifactSaveRequest):
    operation_id: str = Field(min_length=1, max_length=256)


class WritingRevisionChangeRequest(WritingProjectModel):
    paragraph_id: str = Field(min_length=1, max_length=256)
    replacement_markdown: str = Field(default="", max_length=100_000)
    rationale: str = Field(default="", max_length=20_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    category: str = Field(default="suggestion", max_length=64)


class WritingRevisionPreviewRequest(WritingProjectModel):
    expected_version: int = Field(ge=1)
    changes: list[WritingRevisionChangeRequest] = Field(min_length=1, max_length=128)


class WritingParagraph(WritingProjectModel):
    paragraph_id: str = Field(min_length=1, max_length=256)
    markdown: str = Field(default="", max_length=100_000)
    content_hash: str = Field(min_length=1, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_length=128)


class WritingRevisionPreviewResponse(WritingProjectModel):
    project_id: str
    section_id: str
    base_version: int
    revision_ref: ArtifactRef
    before: list[WritingParagraph] = Field(default_factory=list)
    after: list[WritingParagraph] = Field(default_factory=list)


class WritingSectionSnapshot(WritingProjectModel):
    section_id: str = Field(min_length=1, max_length=256)
    version: int = Field(ge=1)
    title: str = Field(default="", max_length=1000)
    markdown: str = Field(default="", max_length=200_000)
    paragraphs: list[WritingParagraph] = Field(default_factory=list, max_length=2048)
    artifact_ref: ArtifactRef
    references: list[ReferenceRecord] = Field(default_factory=list, max_length=512)
    verification_status: str = Field(default="unverified", max_length=64)
    created_at: str


class WritingProjectSnapshot(WritingProjectModel):
    project_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=1000)
    writing_goal: str = Field(default="", max_length=20_000)
    outline_ref: ArtifactRef | None = None
    outline_version: int = Field(default=0, ge=0)
    sections: list[WritingSectionSnapshot] = Field(default_factory=list, max_length=512)
    created_at: str
    updated_at: str


class WritingProjectListResponse(WritingProjectModel):
    total: int = Field(ge=0)
    projects: list[WritingProjectSnapshot] = Field(default_factory=list, max_length=512)


class WritingOperationReceipt(WritingProjectModel):
    operation_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    section_id: str = Field(min_length=1, max_length=256)
    result_version: int = Field(ge=1)
    artifact_ref: ArtifactRef
    replayed: bool = False


class WritingExportResponse(WritingProjectModel):
    project_id: str
    markdown: str = Field(max_length=1_000_000)
    references: list[ReferenceRecord] = Field(default_factory=list, max_length=2048)
    outline_version: int = Field(default=0, ge=0)
    section_versions: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "WritingArtifactSaveRequest",
    "WritingExportResponse",
    "WritingOperationReceipt",
    "WritingParagraph",
    "WritingProjectCreateRequest",
    "WritingProjectListResponse",
    "WritingProjectSnapshot",
    "WritingRevisionApplyRequest",
    "WritingRevisionChangeRequest",
    "WritingRevisionPreviewRequest",
    "WritingRevisionPreviewResponse",
    "WritingSectionSnapshot",
]
