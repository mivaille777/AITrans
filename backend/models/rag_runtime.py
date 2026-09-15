from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RagModelId = Literal[
    "qwen3-embedding-0.6b",
    "qwen3-reranker-0.6b",
]
RagModelState = Literal[
    "not_installed",
    "downloading",
    "installed",
    "invalid",
]
RagModelSource = Literal[
    "none",
    "managed",
    "huggingface_cache",
]


class RagRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagModelStatusResponse(RagRuntimeContract):
    model_id: RagModelId
    display_name: str
    repository_id: str
    state: RagModelState
    installed: bool
    verified: bool
    source: RagModelSource = "none"
    removable: bool = False
    path: str = ""
    disk_usage_bytes: int = Field(default=0, ge=0)
    # ``verified`` means the model artifacts are complete. ``runtime_ready``
    # is set only after this backend process has loaded the model and run a
    # minimal inference probe.
    runtime_ready: bool = False
    runtime_error: str = ""
    error: str = ""


class RagModelListResponse(RagRuntimeContract):
    models_root: str
    models: list[RagModelStatusResponse] = Field(default_factory=list)


class RagModelOperationResponse(RagRuntimeContract):
    model: RagModelStatusResponse
    changed: bool


__all__ = [
    "RagModelId",
    "RagModelListResponse",
    "RagModelOperationResponse",
    "RagModelSource",
    "RagModelState",
    "RagModelStatusResponse",
    "RagRuntimeContract",
]
