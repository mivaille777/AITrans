from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CompanionQueryRoute(str, Enum):
    SYSTEM_IDENTITY = "system_identity"
    GENERAL = "general"
    KNOWLEDGE_CATALOG = "knowledge_catalog"
    READING_CONTEXT = "reading_context"
    DOCUMENT_SCOPED_SEARCH = "document_scoped_search"
    KNOWLEDGE_SEARCH = "knowledge_search"


class GroundingPolicy(str, Enum):
    NONE = "none"
    MANIFEST = "manifest"
    EVIDENCE = "evidence"


@dataclass(frozen=True, slots=True)
class CompanionExecutionPlan:
    route: CompanionQueryRoute
    grounding_policy: GroundingPolicy
    use_knowledge: bool
    document_ids: tuple[str, ...]
    reason: str
