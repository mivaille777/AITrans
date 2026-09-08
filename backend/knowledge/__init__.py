"""Card-first knowledge domain for AITrans."""

from backend.knowledge.domain import (
    AI_SUGGESTIBLE_RELATION_TYPES,
    KNOWN_RELATION_TYPES,
    KnowledgeCollection,
    KnowledgeItem,
    KnowledgeItemType,
    KnowledgeRelation,
    KnowledgeRelationOrigin,
    KnowledgeRelationSuggestion,
    KnowledgeRelationSuggestionStatus,
    KnowledgeTag,
    PaperMetadata,
    ReadingStatus,
)
from backend.knowledge.repository import KnowledgeRepository, SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.knowledge.suggestion_repository import (
    SqliteKnowledgeRelationSuggestionRepository,
)

__all__ = [
    "AI_SUGGESTIBLE_RELATION_TYPES",
    "KNOWN_RELATION_TYPES",
    "KnowledgeCollection",
    "KnowledgeItem",
    "KnowledgeItemType",
    "KnowledgeRelation",
    "KnowledgeRelationOrigin",
    "KnowledgeRelationSuggestion",
    "KnowledgeRelationSuggestionStatus",
    "KnowledgeRepository",
    "KnowledgeTag",
    "KnowledgeWorkspaceService",
    "PaperMetadata",
    "ReadingStatus",
    "SqliteKnowledgeRelationSuggestionRepository",
    "SqliteKnowledgeRepository",
]
