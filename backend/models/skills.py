"""Contracts for the local Skill library; skills are files, not executable plugins."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillRecord(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    valid: bool
    diagnostics: list[str]
    metadata: dict
    file_count: int
    updated_at: str


class SkillFile(BaseModel):
    path: str
    size: int


class SkillDetail(SkillRecord):
    files: list[SkillFile]


class SkillLibrary(BaseModel):
    skills: list[SkillRecord]
    storage_root: str


class SkillFileContent(SkillFile):
    content: str | None
    revision: str
    language: str
    previewable: bool


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSkillRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1024)


class ImportSkillRequest(StrictRequest):
    path: str | None = Field(default=None, min_length=1, max_length=4096)
    content: str | None = Field(default=None, max_length=2 * 1024 * 1024)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.path is None) == (self.content is None):
            raise ValueError(
                "Provide either a local directory path or SKILL.md content."
            )
        return self


class SetSkillEnabledRequest(StrictRequest):
    enabled: bool


class WriteSkillFileRequest(StrictRequest):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=2 * 1024 * 1024)
    # null means create-only; existing files require their last read revision.
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SkillDescriptor(BaseModel):
    id: str
    description: str
    category: str
    triggers: list[str]
    context_modes: list[str]
    invocation: Literal["auto", "manual"]
    revision: str


class SkillDomain(BaseModel):
    id: str
    description: str
    count: int


class SkillCatalog(BaseModel):
    domains: list[SkillDomain]
    eligible_count: int
    revision: str
    disclosure_level: Literal["domains"] = "domains"


class SkillCandidate(SkillDescriptor):
    score: int
    reason: str


class SkillRouteRequest(StrictRequest):
    query: str = Field(min_length=1, max_length=6000)
    context_mode: Literal["general", "reading"] = "general"
    category: str | None = Field(default=None, max_length=64)


class SkillRoutePreview(BaseModel):
    catalog: SkillCatalog
    selected_domains: list[str]
    candidates: list[SkillCandidate]
    explicit_ids: list[str]
    diagnostics: list[str]
    disclosure_level: Literal["metadata"] = "metadata"
    body_loaded: bool = False
