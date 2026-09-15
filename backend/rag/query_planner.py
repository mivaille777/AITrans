from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.errors import AIError
from app.ai.prompt_registry import PromptRegistry, PromptSpec
from backend.rag.fusion import rrf_fuse
from backend.rag.models import RetrievalResult

MAX_RAG_SUBQUERIES = 3
MAX_RAG_RETRIEVAL_QUERIES = 3
MAX_RAG_HISTORY_MESSAGES = 8
MAX_RAG_HISTORY_CHARS = 6_000
RAG_QUERY_PLANNER_PROMPT = PromptSpec(
    name="rag.query_planner",
    version="1.3.0",
    system_prompt=(
        "Rewrite the current knowledge-retrieval request into a standalone search query. "
        "Use the bounded conversation history only to resolve pronouns, ellipsis, document "
        "references, and follow-up intent; never answer the question from history. Return one "
        "JSON object only with original_query, rewritten_query, and subqueries. The rewritten "
        "query must preserve explicit document titles and technical terms. Make academic document "
        "structure explicit when the user targets a section or artifact: References/Bibliography/"
        "Works Cited for cited literature, Conclusion/Conclusions for final findings, Discussion, "
        "Limitations, Future Work, Table, Figure, Equation, or Formula as appropriate. For requests "
        "about a paper's final conclusion, findings, limitations, discussion, future work, "
        "references, bibliography, tables, figures, equations, or formulas, include the "
        "corresponding English structural retrieval terms even when the user asks in another "
        "language. Add subqueries only when they improve recall, keep retrieval non-recursive, "
        "and never answer the user's question."
    ),
    temperature=0.0,
    max_tokens=512,
)


class RagQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    original_query: str = Field(min_length=1, max_length=4_000)
    rewritten_query: str = Field(min_length=1, max_length=4_000)
    subqueries: list[str] = Field(default_factory=list, max_length=MAX_RAG_SUBQUERIES)

    @model_validator(mode="after")
    def normalize_subqueries(self) -> RagQueryPlan:
        normalized: list[str] = []
        seen: set[str] = {self.rewritten_query.casefold()}
        for raw in self.subqueries:
            query = str(raw or "").strip()
            key = query.casefold()
            if query and key not in seen:
                normalized.append(query[:4_000])
                seen.add(key)
        self.subqueries = normalized[:MAX_RAG_SUBQUERIES]
        return self

    @property
    def retrieval_queries(self) -> tuple[str, ...]:
        queries = [self.rewritten_query, *self.subqueries]
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in queries:
            query = str(raw or "").strip()
            key = query.casefold()
            if query and key not in seen:
                normalized.append(query)
                seen.add(key)
            if len(normalized) >= MAX_RAG_RETRIEVAL_QUERIES:
                break
        return tuple(normalized)


def _fallback_plan(query: str) -> RagQueryPlan:
    normalized = str(query or "").strip()
    return RagQueryPlan(
        original_query=normalized,
        rewritten_query=normalized,
        subqueries=[],
    )


def _complex_query(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    patterns = (
        r"\bversus\b",
        r"\bvs\.?\b",
        r"\bcompare\b",
        r"\bdifference\b",
        r"\bwhy\b.*\bthan\b",
        r"为什么.*比",
        r"比较|对比|区别|差异",
        r"以及|同时|分别",
    )
    return len(normalized) >= 180 or any(
        re.search(pattern, normalized) for pattern in patterns
    )


def _bounded_history(
    history: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> list[dict[str, str]]:
    bounded: list[dict[str, str]] = []
    remaining = MAX_RAG_HISTORY_CHARS
    for raw_role, raw_content in reversed(tuple(history)[-MAX_RAG_HISTORY_MESSAGES:]):
        content = str(raw_content or "").strip()
        if not content or remaining <= 0:
            continue
        content = content[-remaining:]
        role_value = getattr(raw_role, "value", raw_role)
        role = str(role_value or "").strip().lower()
        if role not in {"user", "assistant"}:
            role = "user"
        bounded.append({"role": role, "content": content})
        remaining -= len(content)
    bounded.reverse()
    return bounded


class RagQueryPlanner:
    """One-shot bounded standalone-query rewrite and optional decomposition."""

    def __init__(
        self,
        *,
        text_service: Any,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self._text_service = text_service
        self._prompt_registry = prompt_registry or PromptRegistry(
            (RAG_QUERY_PLANNER_PROMPT,)
        )

    @property
    def prompt_id(self) -> str:
        return self._prompt_registry.get("rag.query_planner").prompt_id

    def _client(self) -> Any:
        provider = getattr(self._text_service, "provider", None)
        client = getattr(provider, "client", None)
        complete = getattr(client, "complete", None)
        if not callable(complete):
            raise TypeError("planner route does not expose a chat completion client")
        return client

    @staticmethod
    def _parse(raw: str, original_query: str) -> RagQueryPlan:
        candidate = str(raw or "").strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        decoded = json.loads(candidate)
        if not isinstance(decoded, dict):
            raise TypeError("query planner response must be an object")
        raw_subqueries = decoded.get("subqueries", [])
        if isinstance(raw_subqueries, list):
            decoded["subqueries"] = raw_subqueries[:MAX_RAG_SUBQUERIES]
        decoded["original_query"] = original_query
        return RagQueryPlan.model_validate(decoded)

    def plan(
        self,
        query: str,
        *,
        history: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
    ) -> RagQueryPlan:
        fallback = _fallback_plan(query)
        spec = self._prompt_registry.get("rag.query_planner")
        prompt = json.dumps(
            {
                "current_query": fallback.original_query,
                "conversation_history": _bounded_history(history),
                "max_retrieval_queries": MAX_RAG_RETRIEVAL_QUERIES,
                "max_subqueries": MAX_RAG_RETRIEVAL_QUERIES - 1,
                "policy": {
                    "standalone_rewrite": True,
                    "resolve_follow_up_references": True,
                    "preserve_document_structure": True,
                    "decompose": _complex_query(query),
                    "recursive_decomposition": False,
                    "answer_generation": False,
                },
            },
            ensure_ascii=False,
        )
        try:
            raw = self._client().complete(
                system_prompt=spec.system_prompt,
                user_prompt=prompt,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
            )
            return self._parse(raw, fallback.original_query)
        except (
            AIError,
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
            ValidationError,
        ):
            return fallback


def merge_query_results(
    original_query: str,
    results: list[RetrievalResult],
    *,
    limit: int,
) -> RetrievalResult:
    if limit <= 0:
        raise ValueError("multi-query result limit must be positive")
    if not results:
        raise ValueError("multi-query retrieval requires at least one result")
    started = perf_counter()
    ranked_lists = [result.candidates for result in results if result.candidates]
    unique_count = len(
        {candidate.chunk.chunk_id for ranked in ranked_lists for candidate in ranked}
    )
    candidates = rrf_fuse(ranked_lists, limit=max(1, unique_count))
    best_rerank: dict[str, float] = {}
    for ranked in ranked_lists:
        for candidate in ranked:
            if candidate.rerank_score is not None:
                chunk_id = candidate.chunk.chunk_id
                best_rerank[chunk_id] = max(
                    best_rerank.get(chunk_id, float("-inf")),
                    candidate.rerank_score,
                )
    candidates = [
        candidate.model_copy(
            update={"rerank_score": best_rerank.get(candidate.chunk.chunk_id)}
        )
        for candidate in candidates
    ]
    candidates.sort(
        key=lambda candidate: (
            -float(candidate.fusion_score or 0.0),
            -float(
                candidate.rerank_score
                if candidate.rerank_score is not None
                else float("-inf")
            ),
            candidate.chunk.chunk_id,
        )
    )
    candidates = [
        candidate.model_copy(update={"rank": rank})
        for rank, candidate in enumerate(candidates[:limit], start=1)
    ]
    fallback_reasons = [
        str(result.metadata.get("fallback_reason", "") or "")
        for result in results
        if result.metadata.get("fallback_reason")
    ]
    reranker_fallback_reasons = [
        str(result.metadata.get("reranker_fallback_reason", "") or "")
        for result in results
        if result.metadata.get("reranker_fallback_reason")
    ]
    return RetrievalResult(
        query=original_query,
        candidates=candidates,
        retrieval_strategy="multi-query"
        if len(results) > 1
        else results[0].retrieval_strategy,
        elapsed_ms=sum(result.elapsed_ms for result in results)
        + (perf_counter() - started) * 1000,
        metadata={
            "query_count": len(results),
            "retrieval_queries": [result.query for result in results],
            "strategies": [result.retrieval_strategy for result in results],
            "fallback_reason": "; ".join(fallback_reasons),
            "reranker_applied": any(
                bool(result.metadata.get("reranker_applied")) for result in results
            ),
            "reranker_fallback_reason": "; ".join(reranker_fallback_reasons),
            "multi_query_fusion": len(results) > 1,
        },
    )


__all__ = [
    "MAX_RAG_HISTORY_CHARS",
    "MAX_RAG_HISTORY_MESSAGES",
    "MAX_RAG_RETRIEVAL_QUERIES",
    "MAX_RAG_SUBQUERIES",
    "RAG_QUERY_PLANNER_PROMPT",
    "RagQueryPlan",
    "RagQueryPlanner",
    "merge_query_results",
]
