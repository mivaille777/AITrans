"""Safe request and response contracts for local LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AIProviderName = Literal[
    "deepseek",
    "openai",
    "google",
    "mistral",
    "groq",
    "openrouter",
    "together",
    "qwen",
    "openai_compatible",
]
class LLMProviderOption(BaseModel):
    id: AIProviderName
    label: str
    requires_base_url: bool
    default_model: str
    default_base_url: str


class LLMSettingsResponse(BaseModel):
    provider: AIProviderName
    model: str
    base_url: str
    providers: list[LLMProviderOption] = Field(default_factory=list)


class LLMModelOption(BaseModel):
    id: str = Field(min_length=1, max_length=512)


class LLMModelsResponse(BaseModel):
    provider: AIProviderName
    current_model: str = ""
    available: bool = False
    models: list[LLMModelOption] = Field(default_factory=list)
    detail: str = ""


class LLMSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: AIProviderName
    model: str = Field(min_length=1, max_length=256)
    base_url: str = Field(default="", max_length=2048)


class LLMRuntimeStatusResponse(BaseModel):
    state: Literal["available", "calling", "unavailable"]
    provider: str = ""
    model: str = ""
    detail: str = ""
    active_requests: int = Field(default=0, ge=0)


__all__ = [
    "AIProviderName",
    "LLMModelOption",
    "LLMModelsResponse",
    "LLMProviderOption",
    "LLMRuntimeStatusResponse",
    "LLMSettingsResponse",
    "LLMSettingsUpdateRequest",
]
