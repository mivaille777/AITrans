from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
    KnowledgeScopeStrategy,
)


_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|你好|您好|嗨|谢谢|早上好|晚上好)[!！,.。\s]*$",
    re.IGNORECASE,
)
_CATALOG_RE = re.compile(
    r"(?:知识库|知识库中|knowledge\s*(?:base|library))"
    r".{0,24}(?:有什么|有哪些|内容|目录|清单|文档|documents?|papers?)"
    r"|(?:list|show|enumerate)\s+(?:my\s+)?(?:knowledge|documents?|papers?)",
    re.IGNORECASE,
)
_EXPLICIT_KNOWLEDGE_RE = re.compile(
    r"(?:知识库|知识库中|knowledge\s*(?:base|library)|向量库|检索)"
    r"|(?:相关工作|相关论文|文献|论文们|跨文档|跨论文|比较.+(?:论文|文献|文档))"
    r"|(?:找|搜索|检索|查找|寻找).{0,16}(?:论文|文献|证据|支持|反驳)"
    r"|(?:related\s+work|related\s+papers?|cross[-\s]document|evidence|verify|support|refute|literature|search)\b",
    re.IGNORECASE,
)
_LOCAL_CONTEXT_RE = re.compile(
    r"(?:当前|这段|这句话|选中|当前选中|摘要|公式|段落|本节|此处|this\s+(?:passage|sentence|paragraph|formula)|selected)",
    re.IGNORECASE,
)
_CONTEXT_INSUFFICIENT_RE = re.compile(
    r"(?:完整|全文|实验结果|结果部分|讨论部分|局限|其他文献|其他论文|更多证据|是否成立|是否支持|验证结论|完整方法)"
    r"|(?:full\s+(?:paper|text|results)|experimental\s+results?|discussion|limitations?|other\s+papers?|more\s+evidence|does.{0,20}support)",
    re.IGNORECASE,
)
_SIMPLE_REWRITE_RE = re.compile(
    r"(?:改写|重写|润色|翻译|总结|概括|解释一下这(?:段|句话|个公式)|rewrite|polish|translate|summarize|explain\s+this)",
    re.IGNORECASE,
)


def _text(value: object, *, limit: int = 4_000) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _scope_strategy(
    *,
    context_mode: str,
    attached_document: str,
    explicit_scope_count: int,
    workspace_available: bool,
) -> KnowledgeScopeStrategy:
    if explicit_scope_count > 0:
        return KnowledgeScopeStrategy.EXPLICIT_DOCUMENTS
    if context_mode == "research" and workspace_available:
        return KnowledgeScopeStrategy.RESEARCH_WORKSPACE
    if attached_document:
        return KnowledgeScopeStrategy.ATTACHED_DOCUMENT
    if context_mode == "research" and workspace_available:
        return KnowledgeScopeStrategy.RESEARCH_WORKSPACE
    return KnowledgeScopeStrategy.GLOBAL_KNOWLEDGE


class KnowledgeAccessRouter:
    """Deterministic-first retrieval decision with a narrow semantic seam."""

    def __init__(self, semantic_router: Any | None = None) -> None:
        self._semantic_router = semantic_router
        self.semantic_calls = 0

    def deterministic_route(
        self,
        *,
        user_message: str,
        context_mode: str = "general",
        policy: KnowledgeAccessPolicy | str = KnowledgeAccessPolicy.AUTO,
        reading_context_available: bool = False,
        attached_document: str = "",
        explicit_scope_count: int = 0,
        workspace_available: bool = False,
        knowledge_available: bool = True,
    ) -> KnowledgeAccessDecision | None:
        message = _text(user_message)
        mode = KnowledgeAccessPolicy(policy)
        normalized_context_mode = _text(context_mode, limit=64).lower() or "general"
        attached = _text(attached_document, limit=256)
        strategy = _scope_strategy(
            context_mode=normalized_context_mode,
            attached_document=attached,
            explicit_scope_count=max(0, int(explicit_scope_count)),
            workspace_available=bool(workspace_available),
        )

        if mode is KnowledgeAccessPolicy.NEVER:
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="explicit_never",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                query=message,
            )
        if mode is KnowledgeAccessPolicy.ALWAYS:
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=True,
                reason_code="explicit_always",
                scope_strategy=strategy,
                confidence=1.0,
                query=message,
            )
        if not message:
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="current_context_sufficient",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                query="",
            )
        if _CATALOG_RE.search(message):
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="catalog_request",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                confidence=0.98,
                query=message,
            )
        if _GREETING_RE.fullmatch(message):
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="current_context_sufficient",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                confidence=0.99,
                query=message,
            )
        if _EXPLICIT_KNOWLEDGE_RE.search(message):
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=True,
                reason_code=(
                    "cross_document_request"
                    if re.search(r"跨文档|跨论文|比较.+(?:论文|文献|文档)|cross[-\s]document", message, re.I)
                    else "knowledge_request"
                ),
                scope_strategy=strategy,
                confidence=0.96 if knowledge_available else 0.7,
                query=message,
            )
        if _SIMPLE_REWRITE_RE.search(message) and not _CONTEXT_INSUFFICIENT_RE.search(message):
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="current_context_sufficient" if reading_context_available else "current_context_sufficient",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                confidence=0.94,
                query=message,
            )
        if reading_context_available and _LOCAL_CONTEXT_RE.search(message):
            if _CONTEXT_INSUFFICIENT_RE.search(message):
                return KnowledgeAccessDecision(
                    mode=mode,
                    should_retrieve=True,
                    reason_code="current_context_insufficient",
                    scope_strategy=(
                        KnowledgeScopeStrategy.ATTACHED_DOCUMENT
                        if attached
                        else strategy
                    ),
                    confidence=0.9,
                    query=message,
                )
            return KnowledgeAccessDecision(
                mode=mode,
                should_retrieve=False,
                reason_code="current_context_sufficient",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                confidence=0.88,
                query=message,
            )
        return None

    def semantic_route(
        self,
        *,
        user_message: str,
        context_mode: str = "general",
        policy: KnowledgeAccessPolicy | str = KnowledgeAccessPolicy.AUTO,
        reading_context_available: bool = False,
        attached_document: str = "",
        explicit_scope_count: int = 0,
        workspace_available: bool = False,
        knowledge_available: bool = True,
        context_summary: str = "",
    ) -> KnowledgeAccessDecision:
        mode = KnowledgeAccessPolicy(policy)
        if self._semantic_router is not None:
            self.semantic_calls += 1
            payload = {
                "user_message": _text(user_message),
                "context_mode": _text(context_mode, limit=64).lower() or "general",
                "reading_context_available": bool(reading_context_available),
                "attached_document": _text(attached_document, limit=256),
                "explicit_scope_count": max(0, int(explicit_scope_count)),
                "workspace_available": bool(workspace_available),
                "knowledge_available": bool(knowledge_available),
                "context_summary": _text(context_summary, limit=1_000),
            }
            try:
                invoke = self._semantic_router
                if not callable(invoke):
                    invoke = getattr(self._semantic_router, "route", None)
                if not callable(invoke):
                    raise TypeError("semantic router is not callable")
                raw = invoke(**payload)
                if hasattr(raw, "model_dump"):
                    raw = raw.model_dump()
                if isinstance(raw, Mapping):
                    return KnowledgeAccessDecision.model_validate(
                        {
                            "mode": raw.get("mode", mode.value),
                            "should_retrieve": bool(raw.get("should_retrieve", False)),
                            "reason_code": raw.get("reason_code", "semantic_router_required"),
                            "scope_strategy": raw.get(
                                "scope_strategy",
                                _scope_strategy(
                                    context_mode=payload["context_mode"],
                                    attached_document=payload["attached_document"],
                                    explicit_scope_count=payload["explicit_scope_count"],
                                    workspace_available=payload["workspace_available"],
                                ).value,
                            ),
                            "confidence": raw.get("confidence"),
                            "query": raw.get("query", payload["user_message"]),
                        }
                    )
            except Exception:
                # A failed semantic call must never make the run fail.
                pass

        return self._failure_fallback(
            user_message=user_message,
            context_mode=context_mode,
            policy=mode,
            attached_document=attached_document,
            workspace_available=workspace_available,
        )

    def route(self, **kwargs: Any) -> KnowledgeAccessDecision:
        deterministic_kwargs = dict(kwargs)
        deterministic_kwargs.pop("context_summary", None)
        deterministic = self.deterministic_route(**deterministic_kwargs)
        if deterministic is not None:
            return deterministic
        return self.semantic_route(**kwargs)

    @staticmethod
    def _failure_fallback(
        *,
        user_message: str,
        context_mode: str,
        policy: KnowledgeAccessPolicy,
        attached_document: str,
        workspace_available: bool,
    ) -> KnowledgeAccessDecision:
        mode = _text(context_mode, limit=64).lower() or "general"
        if policy is KnowledgeAccessPolicy.NEVER:
            return KnowledgeAccessDecision(
                mode=policy,
                should_retrieve=False,
                reason_code="explicit_never",
                scope_strategy=KnowledgeScopeStrategy.NONE,
                query=_text(user_message),
            )
        if mode == "research" and workspace_available:
            strategy = KnowledgeScopeStrategy.RESEARCH_WORKSPACE
            reason = "research_grounding_required"
            retrieve = True
        elif mode == "reading" and _text(attached_document):
            strategy = KnowledgeScopeStrategy.ATTACHED_DOCUMENT
            reason = "document_grounding_required"
            retrieve = True
        else:
            strategy = KnowledgeScopeStrategy.NONE
            reason = "current_context_sufficient"
            retrieve = False
        return KnowledgeAccessDecision(
            mode=policy,
            should_retrieve=retrieve,
            reason_code=reason,  # type: ignore[arg-type]
            scope_strategy=strategy,
            query=_text(user_message),
        )


__all__ = ["KnowledgeAccessRouter"]
