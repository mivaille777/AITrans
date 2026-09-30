from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

RagQueryType = Literal["keyword", "semantic", "multi-hop", "no-answer"]
_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])(?:10\.\d{4,9}/[^\s\"<>]+|[A-Z][A-Z0-9_-]{1,15}|"
    r"[A-Za-z]+\d+[A-Za-z0-9_-]*)(?![A-Za-z0-9_])"
)
_QUOTED = re.compile(r'["“《]([^"”》\n]{2,200})["”》]')
_MULTI_HOP = re.compile(
    r"\b(?:compare|versus|difference|cross[-\s]document|multi[-\s]hop)\b"
    r"|跨文档|跨论文|多跳|比较|对比|区别|差异|为什么.*比|\bwhy\b.{0,80}\bthan\b",
    re.IGNORECASE,
)


def normalize_query(query: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", query).split())


def protected_query_terms(query: str) -> tuple[str, ...]:
    normalized = normalize_query(query)
    return tuple(
        dict.fromkeys([*_IDENTIFIER.findall(normalized), *_QUOTED.findall(normalized)])
    )


def classify_query(query: str) -> RagQueryType:
    normalized = normalize_query(query)
    if not normalized:
        return "no-answer"
    if _MULTI_HOP.search(normalized):
        return "multi-hop"
    return "keyword" if protected_query_terms(normalized) else "semantic"


@dataclass(frozen=True)
class RagQueryRoute:
    query_type: RagQueryType
    reason: str
    enabled: bool
    document_ids: tuple[str, ...] | None
    max_queries: int = 3
    max_retrieval_attempts: int = 3
    should_retrieve: bool = True
    dense_enabled: bool = True
    sparse_enabled: bool = True
    graph_enabled: bool | None = None

    @property
    def retrieval_kwargs(self) -> dict[str, bool | None]:
        if not self.enabled:
            return {}
        return {
            "dense_enabled": self.dense_enabled,
            "sparse_enabled": self.sparse_enabled,
            "graph_enabled": self.graph_enabled,
        }


class RagQueryRouter:
    """Optional channel budgets; scope is a trusted input, never a prediction."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def route(
        self, query: str, *, allowed_document_ids: tuple[str, ...] | None = None
    ) -> RagQueryRoute:
        scope = tuple(allowed_document_ids) if allowed_document_ids is not None else None
        query_type = classify_query(query)
        if scope == () or query_type == "no-answer":
            return RagQueryRoute(
                query_type="no-answer",
                reason="empty_scope" if scope == () else "empty_query",
                enabled=self.enabled,
                document_ids=scope,
                should_retrieve=False,
                max_queries=0,
            )
        if not self.enabled:
            return RagQueryRoute(query_type, "router_disabled", False, scope)
        return RagQueryRoute(
            query_type=query_type,
            reason={
                "keyword": "literal_identifier",
                "semantic": "hybrid_semantic_query",
                "multi-hop": "bounded_multi_hop_query",
            }[query_type],
            enabled=True,
            document_ids=scope,
            max_queries=1 if query_type == "keyword" else 3,
            max_retrieval_attempts=2 if query_type == "keyword" else 3,
            dense_enabled=query_type != "keyword",
            graph_enabled=None if query_type == "multi-hop" else False,
        )
