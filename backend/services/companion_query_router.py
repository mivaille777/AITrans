from __future__ import annotations

import re
from collections.abc import Iterable

from backend.models.companion_routing import (
    CompanionExecutionPlan,
    CompanionQueryRoute,
    GroundingPolicy,
)


_IDENTITY_PATTERNS = (
    r"^(?:我|你)是谁[？?。.!！]?$",
    r"^你能做什么[？?。.!！]?$",
    r"^你是什么(?:模型|助手)[？?。.!！]?$",
    r"^who are you[?.!]*$",
    r"^what can you do[?.!]*$",
    r"^what model are you[?.!]*$",
)
_CATALOG_PATTERNS = (
    r"(?:资料库|知识库)(?:里|中)?(?:有|包含|收录)(?:什么|哪些)",
    r"(?:资料库|知识库)(?:里|中)?(?:的)?(?:文档|论文|文件)(?:有)?哪些",
    r"(?:我)?(?:导入|上传|保存)(?:了)?哪些(?:论文|文档|文件)",
    r"(?:我)?有哪些(?:论文|文档|文件)",
    r"(?:list|show).*(?:knowledge base|documents?|papers?|files?)",
    r"what(?:'s| is)?.*knowledge base",
)
_DOCUMENT_PATTERNS = (
    r"(?:这|该)(?:一)?篇(?:论文|文档|文章)",
    r"(?:这|该)(?:个)?(?:文档|文件)",
    r"thiss+(?:paper|document|file|article)",
)
_WHITESPACE = re.compile(r"s+")


class CompanionQueryRouter:
    """Deterministic capability router for Companion chat.

    The router performs no network, embedding, retrieval, or LLM calls.  It only
    decides which capability is eligible for the current request.
    """

    def route(
        self,
        query: str,
        *,
        knowledge_enabled: bool = False,
        reading_attached: bool = False,
        document_ids: Iterable[str] = (),
    ) -> CompanionExecutionPlan:
        normalized_query = self._normalize(query)
        normalized_ids = tuple(
            dict.fromkeys(str(item).strip() for item in document_ids if str(item).strip())
        )

        if self._matches(normalized_query, _IDENTITY_PATTERNS):
            return CompanionExecutionPlan(
                route=CompanionQueryRoute.SYSTEM_IDENTITY,
                grounding_policy=GroundingPolicy.NONE,
                use_knowledge=False,
                document_ids=(),
                reason="matched_system_identity",
            )

        if knowledge_enabled and self._matches(normalized_query, _CATALOG_PATTERNS):
            return CompanionExecutionPlan(
                route=CompanionQueryRoute.KNOWLEDGE_CATALOG,
                grounding_policy=GroundingPolicy.MANIFEST,
                use_knowledge=False,
                document_ids=normalized_ids,
                reason="matched_knowledge_catalog",
            )

        if reading_attached:
            return CompanionExecutionPlan(
                route=CompanionQueryRoute.READING_CONTEXT,
                grounding_policy=GroundingPolicy.NONE,
                use_knowledge=False,
                document_ids=(),
                reason="reading_context_attached",
            )

        if knowledge_enabled and (
            normalized_ids or self._matches(normalized_query, _DOCUMENT_PATTERNS)
        ):
            return CompanionExecutionPlan(
                route=CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH,
                grounding_policy=GroundingPolicy.EVIDENCE,
                use_knowledge=True,
                document_ids=normalized_ids,
                reason=(
                    "selected_knowledge_documents"
                    if normalized_ids
                    else "matched_document_scoped_request"
                ),
            )

        if knowledge_enabled:
            return CompanionExecutionPlan(
                route=CompanionQueryRoute.KNOWLEDGE_SEARCH,
                grounding_policy=GroundingPolicy.EVIDENCE,
                use_knowledge=True,
                document_ids=(),
                reason="knowledge_capability_enabled",
            )

        return CompanionExecutionPlan(
            route=CompanionQueryRoute.GENERAL,
            grounding_policy=GroundingPolicy.NONE,
            use_knowledge=False,
            document_ids=(),
            reason="general_chat",
        )

    @staticmethod
    def _normalize(query: str) -> str:
        return _WHITESPACE.sub(" ", str(query or "").strip().lower())

    @staticmethod
    def _matches(query: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, query, flags=re.IGNORECASE) for pattern in patterns)
