from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.ai.chat.models import (
    ChatContext,
    ChatMessage,
    ChatRequest,
    ChatRole,
    ReadingContext,
)
from app.ai.chat.service import AIChatService
from app.ai.chat.stream_service import ProviderStreamingAIChatService
from app.ai.chat.system_context import SYSTEM_CONTEXT, SystemContext
from app.ai.errors import AIConfigurationError
from app.ai.service import AITextService
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.companion_routing import CompanionExecutionPlan, CompanionQueryRoute
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
)
from backend.rag.citation_service import build_evidence_citations
from backend.rag.context_builder import GroundedContextBuilder
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import RetrievalCandidate
from backend.rag.query_planner import RagQueryPlan, merge_query_results
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import (
    build_structural_queries,
    detect_structural_intent,
    promote_structural_candidates,
)
from backend.services.companion_query_router import CompanionQueryRouter
from backend.services.knowledge_access_router import KnowledgeAccessRouter
from backend.services.reading_context_adapter import to_reading_context


@dataclass(frozen=True, slots=True)
class CompanionKnowledgeGrounding:
    evidence: tuple[AgentEvidenceItem, ...] = ()
    citations: tuple[AgentCitationRef, ...] = ()
    tool_context: str = ""
    fallback_reason: str = ""
    debug_metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompanionPreparedExecution:
    plan: CompanionExecutionPlan
    grounding: CompanionKnowledgeGrounding
    knowledge_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_decision: KnowledgeAccessDecision | None = None
    tool_name: str = ""
    tool_context: str = ""
    direct_output_text: str = ""
    catalog_document_count: int = 0


@dataclass(frozen=True, slots=True)
class CompanionChatResult:
    session_id: str
    user_message: str
    output_text: str
    provider: str
    model: str
    request_id: int = 0
    knowledge_enabled: bool = False
    knowledge_access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_decision: KnowledgeAccessDecision | None = None
    knowledge_retrieved: bool = False
    knowledge_document_count: int = 0
    knowledge_chunk_count: int = 0
    knowledge_fallback_reason: str = ""
    evidence: tuple[AgentEvidenceItem, ...] = ()
    citations: tuple[AgentCitationRef, ...] = ()


class CompanionChatService:
    """WebReBuild boundary around the existing provider-neutral chat core."""

    def __init__(
        self,
        *,
        text_service: AITextService | Any | None = None,
        chat_service: AIChatService | Any | None = None,
        stream_service: ProviderStreamingAIChatService | Any | None = None,
        reading_resolver: Any | None = None,
        retrieval_service: Any | None = None,
        query_planner: Any | None = None,
        query_router: CompanionQueryRouter | Any | None = None,
        knowledge_library_service: Any | None = None,
        reading_resolver_factory: Callable[[], Any] | None = None,
        retrieval_service_factory: Callable[[], Any] | None = None,
        query_planner_factory: Callable[[], Any] | None = None,
        knowledge_library_service_factory: Callable[[], Any] | None = None,
        knowledge_access_router: KnowledgeAccessRouter | Any | None = None,
        system_context: SystemContext | Any | None = None,
    ) -> None:
        self._text_service = text_service
        self._chat_service = chat_service
        self._stream_service = stream_service
        self._reading_resolver = reading_resolver
        self._retrieval_service = retrieval_service
        self._query_planner = query_planner
        self._query_router = query_router or CompanionQueryRouter()
        self._knowledge_library_service = knowledge_library_service
        self._reading_resolver_factory = reading_resolver_factory
        self._retrieval_service_factory = retrieval_service_factory
        self._query_planner_factory = query_planner_factory
        self._knowledge_library_service_factory = knowledge_library_service_factory
        self._knowledge_access_router = knowledge_access_router or KnowledgeAccessRouter()
        self._system_context = system_context or SYSTEM_CONTEXT
        self._grounded_context_builder = GroundedContextBuilder()

    @staticmethod
    def _resolve_optional_dependency(
        current: Any | None,
        factory: Callable[[], Any] | None,
    ) -> Any | None:
        if current is not None:
            return current
        if not callable(factory):
            return None
        return factory()

    def _ensure_reading_resolver(self) -> Any | None:
        if self._reading_resolver is None:
            self._reading_resolver = self._resolve_optional_dependency(
                self._reading_resolver,
                self._reading_resolver_factory,
            )
        return self._reading_resolver

    def _ensure_retrieval_service(self) -> Any | None:
        if self._retrieval_service is None:
            self._retrieval_service = self._resolve_optional_dependency(
                self._retrieval_service,
                self._retrieval_service_factory,
            )
        return self._retrieval_service

    def _ensure_query_planner(self) -> Any | None:
        if self._query_planner is None:
            self._query_planner = self._resolve_optional_dependency(
                self._query_planner,
                self._query_planner_factory,
            )
        return self._query_planner

    def _ensure_knowledge_library_service(self) -> Any | None:
        if self._knowledge_library_service is None:
            self._knowledge_library_service = self._resolve_optional_dependency(
                self._knowledge_library_service,
                self._knowledge_library_service_factory,
            )
        return self._knowledge_library_service

    def prepare_execution(
        self,
        *,
        query: str,
        knowledge_enabled: bool | None = None,
        knowledge_access_policy: KnowledgeAccessPolicy | str | None = None,
        document_ids: tuple[str, ...] = (),
        history: tuple[tuple[str, str], ...] = (),
        context_mode: str = "general",
        source_text: str = "",
        phase_callback: Any | None = None,
    ) -> CompanionPreparedExecution:
        policy = self._resolve_knowledge_policy(
            knowledge_access_policy,
            knowledge_enabled,
        )
        legacy_reading_semantics = (
            knowledge_access_policy is None and knowledge_enabled is not None
        )
        reading_context_available = (
            str(context_mode or "").strip().lower() == "reading"
            and bool(str(source_text or "").strip())
        )
        decision = self._knowledge_access_router.route(
            user_message=query,
            context_mode="reading" if reading_context_available else str(context_mode or "general"),
            policy=policy,
            reading_context_available=reading_context_available,
            attached_document="",
            explicit_scope_count=len(tuple(document_ids)),
            workspace_available=False,
            knowledge_available=True,
            context_summary=str(source_text or "")[:1000],
        )
        knowledge_capability_enabled = (
            decision.should_retrieve
            or decision.reason_code == "catalog_request"
            or policy is KnowledgeAccessPolicy.ALWAYS
        )
        plan = self._query_router.route(
            query,
            knowledge_enabled=knowledge_capability_enabled,
            reading_attached=reading_context_available
            and (legacy_reading_semantics or not decision.should_retrieve),
            document_ids=document_ids,
        )
        if callable(phase_callback):
            phase_callback("routing", plan)
        grounding = CompanionKnowledgeGrounding()
        tool_name = ""
        tool_context = ""
        direct_output_text = ""
        catalog_document_count = 0
        if plan.route is CompanionQueryRoute.SYSTEM_IDENTITY:
            direct_output_text = self._system_context.identity_response(query)
        elif plan.route is CompanionQueryRoute.KNOWLEDGE_CATALOG:
            direct_output_text, catalog_document_count = self._render_knowledge_catalog(
                plan.document_ids
            )
        elif plan.use_knowledge:
            if callable(phase_callback):
                phase_callback("retrieving", plan)
            grounding = self.prepare_knowledge(
                query,
                plan.document_ids,
                history=history,
            )
            tool_name = "search_knowledge_base"
            tool_context = grounding.tool_context
        return CompanionPreparedExecution(
            plan=plan,
            grounding=grounding,
            knowledge_policy=policy,
            knowledge_decision=decision,
            tool_name=tool_name,
            tool_context=tool_context,
            direct_output_text=direct_output_text,
            catalog_document_count=catalog_document_count,
        )

    def _render_knowledge_catalog(
        self, document_ids: tuple[str, ...]
    ) -> tuple[str, int]:
        try:
            library = self._ensure_knowledge_library_service()
        except Exception:
            return "本地知识库目录当前不可用。", 0
        if library is None:
            return "本地知识库目录当前不可用。", 0

        try:
            records = list(library.list_documents())
        except Exception:
            return "本地知识库目录当前不可用。", 0
        selected = set(document_ids)
        if selected:
            records = [
                record
                for record in records
                if str(getattr(record, "document_id", "")) in selected
            ]

        if not records:
            return (
                (
                    "当前选择范围内没有可用文档。"
                    if selected
                    else "当前知识库中还没有文档。"
                ),
                0,
            )

        ready_count = sum(
            str(getattr(getattr(record, "status", ""), "value", getattr(record, "status", "")))
            == "ready"
            for record in records
        )
        lines = [
            f"当前知识库共有 {len(records)} 个文档，其中 {ready_count} 个已就绪：",
            "",
        ]
        for index, record in enumerate(records, start=1):
            status = str(
                getattr(
                    getattr(record, "status", ""),
                    "value",
                    getattr(record, "status", ""),
                )
            ) or "unknown"
            title = str(getattr(record, "title", "") or "").strip() or "Untitled document"
            chunk_count = len(tuple(getattr(record, "chunk_ids", ()) or ()))
            section_count = int(getattr(record, "section_count", 0) or 0)
            lines.extend(
                [
                    f"{index}. {title}",
                    f"   - 状态：{status}",
                    f"   - Chunks：{chunk_count}",
                    f"   - Sections：{section_count}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip(), len(records)

    def prepare_knowledge(
        self,
        query: str,
        document_ids: tuple[str, ...] = (),
        *,
        history: tuple[tuple[str, str], ...] = (),
    ) -> CompanionKnowledgeGrounding:
        try:
            retrieval_service = self._ensure_retrieval_service()
        except Exception as exc:
            return CompanionKnowledgeGrounding(
                tool_context="Knowledge retrieval was unavailable. Answer generally if possible and do not cite a source.",
                fallback_reason=f"retrieval_init_failed:{str(exc) or exc.__class__.__name__}",
            )
        if retrieval_service is None:
            return CompanionKnowledgeGrounding(
                tool_context="No relevant knowledge evidence was found. Answer generally if possible and do not cite a source.",
                fallback_reason="retrieval_unavailable",
            )
        normalized_ids = tuple(
            dict.fromkeys(item.strip() for item in document_ids if item.strip())
        )
        filters = (
            VectorSearchFilter(document_ids=list(normalized_ids))
            if normalized_ids
            else None
        )
        try:
            query_planner = self._ensure_query_planner()
        except Exception:
            query_planner = None
        plan = (
            query_planner.plan(query, history=history)
            if query_planner is not None
            else RagQueryPlan(
                original_query=query,
                rewritten_query=query,
                subqueries=[],
            )
        )
        structural_intent = (
            detect_structural_intent(query)
            or detect_structural_intent(plan.rewritten_query)
        )
        retrieval_queries = build_structural_queries(
            plan.retrieval_queries,
            original_query=query,
            intent=structural_intent,
        )
        retrievals = []
        retrieval_errors: list[str] = []
        for retrieval_query in retrieval_queries:
            try:
                retrieve_kwargs: dict[str, Any] = {"filters": filters}
                if structural_intent is not None:
                    retrieve_kwargs.update(
                        {
                            "section_hints": structural_intent.section_aliases,
                            "final_top_k": structural_intent.final_top_k,
                        }
                    )
                    if structural_intent.name == "bibliography":
                        retrieve_kwargs["include_references"] = True
                retrievals.append(
                    retrieval_service.retrieve(
                        retrieval_query,
                        **retrieve_kwargs,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - degrade per retrieval query
                retrieval_errors.append(str(exc) or exc.__class__.__name__)
        if not retrievals:
            detail = "; ".join(retrieval_errors) or "retrieval_failed"
            return CompanionKnowledgeGrounding(
                tool_context="Knowledge retrieval was unavailable. Answer generally if possible and do not cite a source.",
                fallback_reason=detail,
            )

        default_limit = max(
            (len(item.candidates) for item in retrievals),
            default=1,
        )
        merge_limit = (
            structural_intent.final_top_k
            if structural_intent is not None
            else default_limit
        )
        result = merge_query_results(
            query,
            retrievals,
            limit=merge_limit,
        )
        result = promote_structural_candidates(
            result,
            intent=structural_intent,
            limit=merge_limit,
        )
        evidence = build_agent_evidence(result)
        citations = build_evidence_citations(evidence)
        if not evidence:
            return CompanionKnowledgeGrounding(
                tool_context="No relevant knowledge evidence was found. Answer generally if possible and do not cite a source.",
                fallback_reason="no_relevant_evidence",
            )
        context_overrides = {
            f"evidence:{candidate.chunk.chunk_id}": supplemental
            for candidate in result.candidates
            if (supplemental := self._supplemental_context(candidate))
        }
        context = self._grounded_context_builder.build(
            evidence,
            citations,
            context_overrides=context_overrides,
        )
        included = set(context.included_evidence_ids)
        bounded_evidence = tuple(
            item for item in evidence if item.evidence_id in included
        )
        bounded_citations = tuple(
            citation
            for citation in citations
            if all(evidence_id in included for evidence_id in citation.evidence_ids)
        )
        degraded_reason = "; ".join(retrieval_errors)
        if not degraded_reason:
            degraded_reason = str(
                result.metadata.get("reranker_fallback_reason")
                or result.metadata.get("fallback_reason")
                or ""
            )
        return CompanionKnowledgeGrounding(
            evidence=bounded_evidence,
            citations=bounded_citations,
            tool_context=context.text,
            fallback_reason=(
                degraded_reason
                if bounded_evidence
                else "context_budget_exhausted"
            ),
            debug_metadata={
                "retrieval_strategy": str(result.retrieval_strategy or ""),
                "dense_candidates": sum(
                    int(item.metadata.get("dense_count", 0) or 0)
                    for item in retrievals
                ),
                "sparse_candidates": sum(
                    int(item.metadata.get("sparse_count", 0) or 0)
                    for item in retrievals
                ),
                "fused_candidates": sum(
                    int(item.metadata.get("fusion_count", 0) or 0)
                    for item in retrievals
                ),
                "reranked_candidates": len(result.candidates),
                "evidence_count": len(bounded_evidence),
                "embedding_ms": round(
                    sum(float(item.metadata.get("embedding_ms", 0.0) or 0.0) for item in retrievals),
                    3,
                ),
                "dense_search_ms": round(
                    sum(float(item.metadata.get("dense_search_ms", 0.0) or 0.0) for item in retrievals),
                    3,
                ),
                "sparse_search_ms": round(
                    sum(float(item.metadata.get("sparse_search_ms", 0.0) or 0.0) for item in retrievals),
                    3,
                ),
                "fusion_ms": round(
                    sum(float(item.metadata.get("fusion_ms", 0.0) or 0.0) for item in retrievals),
                    3,
                ),
                "rerank_ms": round(
                    sum(float(item.metadata.get("rerank_ms", 0.0) or 0.0) for item in retrievals),
                    3,
                ),
                "total_rag_ms": round(float(result.elapsed_ms or 0.0), 3),
                "selected_chunks": [
                    {
                        "chunk_id": candidate.chunk.chunk_id,
                        "document_id": candidate.chunk.document_id,
                        "title": candidate.chunk.title,
                        "section": candidate.chunk.section_heading,
                        "page": candidate.chunk.page_number,
                        "rank": candidate.rank,
                    }
                    for candidate in result.candidates[:12]
                ],
            },
        )

    @staticmethod
    def _supplemental_context(candidate: RetrievalCandidate) -> str:
        window = candidate.context_window
        if window is None:
            return ""
        segments: list[str] = []
        for chunk in window.chunks:
            if chunk.chunk_id == candidate.chunk.chunk_id:
                continue
            location_parts: list[str] = []
            if chunk.page_number is not None:
                location_parts.append(f"Page {chunk.page_number}")
            if chunk.section_heading.strip():
                location_parts.append(f"Section {chunk.section_heading.strip()}")
            location = " · ".join(location_parts) or "same section"
            segments.append(
                f"[Supplemental {location}]\n{chunk.text.strip()}"
            )
        return "\n\n".join(segment for segment in segments if segment.strip())

    def _ensure_text_service(self) -> AITextService | Any:
        if self._text_service is None:
            self._text_service = AITextService()
        return self._text_service

    def _ensure_chat_service(self) -> AIChatService | Any:
        if self._chat_service is None:
            self._chat_service = AIChatService(self._ensure_text_service())
        return self._chat_service

    def _ensure_stream_service(self) -> ProviderStreamingAIChatService | Any:
        if self._stream_service is None:
            self._stream_service = ProviderStreamingAIChatService(
                self._ensure_text_service()
            )
        return self._stream_service

    @property
    def provider_name(self) -> str:
        service = self._ensure_text_service()
        return str(getattr(service, "provider_name", "")).strip() or "unknown"

    @property
    def model(self) -> str:
        service = self._ensure_text_service()
        return str(getattr(service, "model", "")).strip() or "unknown"

    @property
    def prompt_id(self) -> str:
        service = self._ensure_chat_service()
        return str(getattr(service, "prompt_id", "")).strip()

    def status(self) -> tuple[bool, str, str, str]:
        try:
            return True, self.provider_name, self.model, ""
        except AIConfigurationError as exc:
            return False, "deepseek", "", str(exc)

    def _with_resolved_reading(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = dict(kwargs)
        if str(payload.get("context_mode", "reading")).strip().lower() != "reading":
            return payload

        # Empty source text is an explicit context-free boundary for Agent
        # General/Knowledge/Research requests. Never let the short-lived Reading
        # selection cache repopulate that boundary.
        source_text = str(payload.get("source_text", "") or "")
        if not source_text.strip():
            return payload

        try:
            resolver = self._ensure_reading_resolver()
        except Exception:
            resolver = None
        resolve_for_text = getattr(resolver, "resolve_for_text", None)
        if not callable(resolve_for_text):
            return payload

        try:
            selection = resolve_for_text(source_text)
        except Exception:
            selection = None
        if selection is None:
            return payload

        reading = to_reading_context(selection)
        for key, value in (
            ("resource_url", reading.resource_url),
            ("resource_title", reading.resource_title),
            ("section_heading", reading.section_heading),
            ("context_before", reading.context_before),
            ("context_after", reading.context_after),
            ("source_kind", reading.source_kind),
        ):
            if value and not str(payload.get(key, "") or "").strip():
                payload[key] = value
        return payload

    @staticmethod
    def _build_request(
        *,
        session_id: str,
        user_message: str,
        source_text: str = "",
        translated_text: str = "",
        source_language: str = "auto",
        target_language: str = "zh-CN",
        resource_url: str = "",
        resource_title: str = "",
        section_heading: str = "",
        context_before: str = "",
        context_after: str = "",
        source_kind: str = "",
        history: tuple[tuple[str, str], ...] = (),
        request_id: int = 0,
        context_mode: str = "reading",
        tool_name: str = "",
        tool_context: str = "",
        knowledge_context: dict[str, Any] | None = None,
    ) -> ChatRequest:
        _ = (source_language, target_language)

        messages: list[ChatMessage] = []
        for role_value, content in history[-32:]:
            text = str(content or "").strip()
            if not text:
                continue
            messages.append(
                ChatMessage(
                    role=ChatRole(str(role_value)),
                    content=text,
                )
            )

        has_reading_payload = any(
            str(value or "").strip()
            for value in (
                source_text,
                translated_text,
                resource_url,
                resource_title,
                section_heading,
                context_before,
                context_after,
            )
        )
        grounded = (
            str(context_mode or "").strip().lower() == "reading"
            and has_reading_payload
        )
        context = ChatContext(
            source_text=source_text if grounded else "",
            translated_text=translated_text if grounded else "",
            reading=ReadingContext(
                resource_url=resource_url if grounded else "",
                resource_title=resource_title if grounded else "",
                section_heading=section_heading if grounded else "",
                context_before=context_before if grounded else "",
                context_after=context_after if grounded else "",
                source_kind=source_kind if grounded else "",
            ),
        )
        return ChatRequest(
            session_id=session_id,
            user_message=user_message,
            context=context,
            history=tuple(messages),
            request_id=request_id,
            tool_name=str(tool_name or "").strip(),
            tool_context=str(tool_context or ""),
            knowledge_context=dict(knowledge_context or {}),
        )

    def send(self, **kwargs: Any) -> CompanionChatResult:
        payload = dict(kwargs)
        raw_policy = payload.pop("knowledge_access_policy", None)
        raw_legacy_enabled = payload.pop("knowledge_enabled", None)
        policy = self._resolve_knowledge_policy(raw_policy, raw_legacy_enabled)
        raw_document_ids = payload.pop("knowledge_document_ids", ())
        document_ids = tuple(str(item) for item in raw_document_ids)
        history = tuple(payload.get("history", ()) or ())
        prepared = self.prepare_execution(
            query=str(payload.get("user_message", "")),
            knowledge_access_policy=policy,
            knowledge_enabled=raw_legacy_enabled,
            document_ids=document_ids,
            history=history,
            context_mode=str(payload.get("context_mode", "general") or "general"),
            source_text=str(payload.get("source_text", "") or ""),
        )
        if prepared.tool_name:
            payload["tool_name"] = prepared.tool_name
            payload["tool_context"] = prepared.tool_context
        request = self._build_request(**self._with_resolved_reading(payload))
        if prepared.direct_output_text:
            result = SimpleNamespace(
                session_id=request.session_id,
                user_message=request.user_message,
                output_text=prepared.direct_output_text,
                provider="local",
                model="deterministic",
                request_id=request.request_id,
            )
        else:
            result = self._ensure_chat_service().execute(request)
        grounding = prepared.grounding
        return CompanionChatResult(
            session_id=result.session_id,
            user_message=result.user_message,
            output_text=result.output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            knowledge_enabled=bool(raw_legacy_enabled),
            knowledge_access_policy=prepared.knowledge_policy,
            knowledge_decision=prepared.knowledge_decision,
            knowledge_retrieved=prepared.plan.use_knowledge,
            knowledge_document_count=self._grounding_document_count(grounding),
            knowledge_chunk_count=self._grounding_chunk_count(grounding),
            knowledge_fallback_reason=grounding.fallback_reason,
            evidence=grounding.evidence,
            citations=grounding.citations,
        )

    @staticmethod
    def _resolve_knowledge_policy(
        policy: KnowledgeAccessPolicy | str | None,
        legacy_enabled: bool | None,
    ) -> KnowledgeAccessPolicy:
        if policy is not None:
            return KnowledgeAccessPolicy(policy)
        if legacy_enabled is not None:
            return (
                KnowledgeAccessPolicy.ALWAYS
                if legacy_enabled
                else KnowledgeAccessPolicy.NEVER
            )
        return KnowledgeAccessPolicy.AUTO

    @staticmethod
    def _grounding_document_count(grounding: CompanionKnowledgeGrounding) -> int:
        selected = (grounding.debug_metadata or {}).get("selected_chunks", ())
        identifiers = {
            str(item.get("document_id", "")).strip()
            for item in selected
            if isinstance(item, dict) and str(item.get("document_id", "")).strip()
        }
        if identifiers:
            return len(identifiers)
        return len({item.source_id for item in grounding.evidence if item.source_id})

    @staticmethod
    def _grounding_chunk_count(grounding: CompanionKnowledgeGrounding) -> int:
        selected = (grounding.debug_metadata or {}).get("selected_chunks", ())
        if isinstance(selected, (list, tuple)):
            return len(selected)
        return len(grounding.evidence)

    def stream(self, **kwargs: Any) -> Iterator[str]:
        request = self._build_request(**self._with_resolved_reading(kwargs))
        yield from self._ensure_stream_service().stream(request)

    def close(self) -> None:
        service = self._text_service
        self._stream_service = None
        self._chat_service = None
        self._text_service = None
        if service is not None:
            service.close()
