from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeAccessPolicy(str, Enum):
    """User preference for whether the runtime may access the knowledge base."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class KnowledgeScopeStrategy(str, Enum):
    NONE = "none"
    ATTACHED_DOCUMENT = "attached_document"
    EXPLICIT_DOCUMENTS = "explicit_documents"
    RESEARCH_WORKSPACE = "research_workspace"
    GLOBAL_KNOWLEDGE = "global_knowledge"


KnowledgeDecisionReasonCode = Literal[
    "explicit_always",
    "explicit_never",
    "knowledge_request",
    "cross_document_request",
    "current_context_sufficient",
    "current_context_insufficient",
    "document_grounding_required",
    "research_grounding_required",
    "catalog_request",
    "semantic_router_required",
]


class KnowledgeAccessDecision(BaseModel):
    """Durable runtime decision separating retrieval intent from scope."""

    model_config = ConfigDict(extra="forbid")

    mode: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    should_retrieve: bool = False
    reason_code: KnowledgeDecisionReasonCode = "current_context_sufficient"
    scope_strategy: KnowledgeScopeStrategy = KnowledgeScopeStrategy.NONE
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    query: str = Field(default="", max_length=4_000)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


class ResolvedKnowledgeScope(BaseModel):
    """Trusted retrieval boundary resolved from request context."""

    model_config = ConfigDict(extra="forbid")

    strategy: KnowledgeScopeStrategy = KnowledgeScopeStrategy.NONE
    document_ids: tuple[str, ...] = ()
    workspace_id: str = ""
    research_source_ids: tuple[str, ...] = ()
    allow_global: bool = False
    reason: str = ""

    @field_validator("document_ids", "research_source_ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            return ()
        result: list[str] = []
        seen: set[str] = set()
        for raw in value:
            identifier = str(raw or "").strip()
            if not identifier or identifier in seen:
                continue
            result.append(identifier)
            seen.add(identifier)
        return tuple(result)

    @field_validator("workspace_id", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value or "").strip()


__all__ = [
    "KnowledgeAccessDecision",
    "KnowledgeAccessPolicy",
    "KnowledgeDecisionReasonCode",
    "KnowledgeScopeStrategy",
    "ResolvedKnowledgeScope",
]
