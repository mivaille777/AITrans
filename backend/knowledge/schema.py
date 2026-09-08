"""Knowledge 2.0 domain schema.

Phase 1 foundation:
- Knowledge Card
- Evidence
- Relation
- Agent Event

This module intentionally stays independent from storage implementation so the
existing knowledge repositories can migrate incrementally.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CardType(str, Enum):
    CONCEPT = "concept"
    EVIDENCE = "evidence"
    INSIGHT = "insight"
    QUESTION = "question"


class RelationType(str, Enum):
    SIMILAR = "similar"
    SUPPORT = "support"
    CITES = "cites"
    EXTENDS = "extends"
    CAUSES = "causes"
    HIERARCHY = "hierarchy"
    EVOLVES = "evolves"


class AgentAction(str, Enum):
    CREATE_CARD = "create_card"
    UPDATE_CARD = "update_card"
    CREATE_RELATION = "create_relation"
    MERGE_CARD = "merge_card"
    DELETE_CARD = "delete_card"


class Evidence(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None = None
    quote: str
    page: int | None = None
    section: str | None = None


class KnowledgeRelation(BaseModel):
    id: str
    source_card_id: str
    target_card_id: str
    relation_type: RelationType
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_by: str = "agent"
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeCard(BaseModel):
    id: str
    type: CardType
    title: str
    summary: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    sources: list[Evidence] = Field(default_factory=list)
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentEvent(BaseModel):
    id: str
    agent_name: str
    action: AgentAction
    target_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
