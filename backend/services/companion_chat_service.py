from __future__ import annotations

from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from threading import Event
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.ai.chat.models import (
    ChatContext,
    ChatMessage,
    ChatRequest,
    ChatRole,
    ReadingContext,
)
from app.ai.chat.service import CHAT_SYSTEM_PROMPT, AIChatService, build_chat_prompt
from app.ai.chat.stream_service import ProviderStreamingAIChatService
from app.ai.chat.system_context import SYSTEM_CONTEXT, SystemContext
from app.ai.errors import AIConfigurationError, AITimeoutError
from app.ai.service import AITextService
from backend.agent_core.exceptions import AgentBudgetExceededError
from backend.agent_tools.knowledge import KnowledgeAgentTools
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.companion_routing import (
    CompanionExecutionPlan,
    CompanionQueryRoute,
    GroundingPolicy,
)
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
)
from backend.rag.citation_service import build_evidence_citations
from backend.rag.context_builder import GroundedContextBuilder
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import RetrievalCandidate
from backend.rag.query_planner import (
    MAX_RAG_RETRIEVAL_QUERIES,
    RagQueryPlan,
    RagQueryPlanner,
    merge_query_results,
)
from backend.rag.query_router import RagQueryRoute, RagQueryRouter
from backend.rag.retrieval_service import RetrievalService
from backend.rag.stores.base import VectorSearchFilter
from backend.rag.structure_retrieval import (
    build_structural_queries,
    detect_structural_intent,
    promote_structural_candidates,
)
from backend.services.agent_claim_evidence_verifier import AgentClaimEvidenceVerifier
from backend.services.companion_query_router import CompanionQueryRouter
from backend.services.knowledge_access_router import KnowledgeAccessRouter
from backend.services.knowledge_function_calling import (
    KNOWLEDGE_FUNCTION_PROMPT,
    KnowledgeFunctionState,
    run_knowledge_functions,
)
from backend.services.knowledge_scope_resolver import KnowledgeScopeResolver
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
    knowledge_recovery: dict[str, Any] = field(default_factory=dict)


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
        rag_rewrite_enabled: bool = True,
        rag_router_enabled: bool = False,
        rag_query_router: RagQueryRouter | Any | None = None,
        function_calling_enabled: bool = False,
        knowledge_tools_factory: Callable[[], KnowledgeAgentTools] | None = None,
        skill_runtime_factory: Callable[[], Any] | None = None,
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
        self.function_calling_enabled = bool(function_calling_enabled)
        self._knowledge_tools_factory = knowledge_tools_factory
        self._skill_runtime_factory = skill_runtime_factory
        if not isinstance(rag_rewrite_enabled, bool) or not isinstance(
            rag_router_enabled, bool
        ):
            raise TypeError("RAG rewrite/router settings must be boolean")
        self._rag_rewrite_enabled = rag_rewrite_enabled
        self._rag_query_router = rag_query_router or RagQueryRouter(
            enabled=rag_router_enabled
        )

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
        trace_id: str | None = None,
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
                trace_id=trace_id,
            )
            tool_name = "search_knowledge_base"
            tool_context = grounding.tool_context
            if not grounding.evidence and (
                plan.route is CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH
                or context_mode in {"knowledge", "research"}
            ):
                direct_output_text = "当前文档中没有足够的可用证据回答此问题，请补充资料或稍后重试。"
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
        trace_id: str | None = None,
    ) -> CompanionKnowledgeGrounding:
        trace_id = trace_id or f"companion_{uuid4().hex[:20]}"
        try:
            retrieval_service = self._ensure_retrieval_service()
        except Exception as exc:
            return CompanionKnowledgeGrounding(
                tool_context="Knowledge retrieval was unavailable. Answer generally if possible and do not cite a source.",
                fallback_reason=f"retrieval_init_failed:{str(exc) or exc.__class__.__name__}",
                debug_metadata={"trace_id": trace_id},
            )
        if retrieval_service is None:
            return CompanionKnowledgeGrounding(
                tool_context="No relevant knowledge evidence was found. Answer generally if possible and do not cite a source.",
                fallback_reason="retrieval_unavailable",
                debug_metadata={"trace_id": trace_id},
            )
        normalized_ids = tuple(
            dict.fromkeys(item.strip() for item in document_ids if item.strip())
        )
        filters = (
            VectorSearchFilter(document_ids=list(normalized_ids))
            if normalized_ids
            else None
        )
        scope = normalized_ids or None
        router_error = ""
        try:
            route = self._rag_query_router.route(query, allowed_document_ids=scope)
            if not isinstance(route, RagQueryRoute):
                raise TypeError("query router must return a RagQueryRoute")
            if route.document_ids != scope:
                raise ValueError("query router changed the document scope")
            if route.should_retrieve and not (
                1 <= route.max_queries <= route.max_retrieval_attempts
                <= MAX_RAG_RETRIEVAL_QUERIES
            ):
                raise ValueError("query router exceeded the retrieval budget")
        except Exception as exc:  # noqa: BLE001 - optional route fails back within the same scope
            router_error = str(exc) or exc.__class__.__name__
            route = RagQueryRouter().route(query, allowed_document_ids=scope)
        if not route.should_retrieve:
            return CompanionKnowledgeGrounding(
                fallback_reason=route.reason,
                debug_metadata={"trace_id": trace_id, "query_route": asdict(route), "original_query": query},
            )
        plan = RagQueryPlan(original_query=query, rewritten_query=query)
        planning_started = perf_counter()
        if self._rag_rewrite_enabled and route.max_queries > 1 and not router_error:
            try:
                query_planner = self._ensure_query_planner()
                if query_planner is not None:
                    plan_kwargs: dict[str, Any] = {"history": history}
                    if isinstance(query_planner, RagQueryPlanner):
                        plan_kwargs["single_document_scope"] = (
                            scope is not None and len(scope) == 1
                        )
                    proposed = query_planner.plan(query, **plan_kwargs)
                    if not isinstance(proposed, RagQueryPlan):
                        raise TypeError("query planner must return a RagQueryPlan")
                    plan = RagQueryPlan.model_validate(
                        {**proposed.model_dump(), "original_query": query}
                    )
            except Exception as exc:  # noqa: BLE001 - optional rewrite preserves the original query
                plan = plan.model_copy(
                    update={"fallback_reason": str(exc) or exc.__class__.__name__}
                )
        planning_ms = (perf_counter() - planning_started) * 1000
        structural_intent = detect_structural_intent(query)
        expanded_queries = (
            build_structural_queries(
                plan.rewrites or (query,),
                original_query=query,
                intent=structural_intent,
                max_queries=route.max_queries - 1,
            )
            if self._rag_rewrite_enabled and not (router_error or plan.fallback_reason)
            else ()
        )
        retrieval_queries = tuple(dict.fromkeys((query, *expanded_queries)))[
            :route.max_queries
        ]
        debug_plan = {
            "trace_id": trace_id,
            "query_plan": plan.model_dump(mode="json"),
            "query_route": asdict(route),
            "retrieval_queries": list(retrieval_queries),
            "rewrite_enabled": self._rag_rewrite_enabled,
            "router_fallback_reason": router_error,
            "query_planning_ms": planning_ms,
        }
        retrievals = []
        retrieval_errors: list[str] = []
        for retrieval_query in retrieval_queries:
            try:
                retrieve_kwargs: dict[str, Any] = {
                    "filters": filters.model_copy(deep=True) if filters else None,
                    **route.retrieval_kwargs,
                }
                if isinstance(retrieval_service, RetrievalService) or callable(
                    getattr(retrieval_service, "validate_evidence_candidates", None)
                ):
                    retrieve_kwargs["trace_id"] = trace_id
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
        if (
            route.enabled
            and not retrievals
            and len(retrieval_queries) < route.max_retrieval_attempts
        ):
            debug_plan["router_fallback_reason"] = "routed_channels_failed"
            debug_plan["retrieval_queries"].append(query)
            try:
                retrievals.append(
                    retrieval_service.retrieve(
                        query, filters=filters.model_copy(deep=True) if filters else None,
                        **({"trace_id": trace_id} if isinstance(retrieval_service, RetrievalService) or callable(
                            getattr(retrieval_service, "validate_evidence_candidates", None)
                        ) else {}),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - preserve failures from the original-query fallback
                retrieval_errors.append(str(exc) or exc.__class__.__name__)
        if not retrievals:
            detail = "; ".join(retrieval_errors) or "retrieval_failed"
            return CompanionKnowledgeGrounding(
                tool_context="Knowledge retrieval was unavailable. Answer generally if possible and do not cite a source.",
                fallback_reason=detail,
                debug_metadata=debug_plan,
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
        try:
            validator = getattr(retrieval_service, "validate_evidence_candidates", None)
            if callable(validator):
                validator(result, filters=filters)
            evidence = build_agent_evidence(result)
        except Exception as exc:  # noqa: BLE001 - invalid provenance must fail closed
            return CompanionKnowledgeGrounding(
                tool_context="Knowledge evidence is unavailable. Do not claim a document-grounded answer or invent citations.",
                fallback_reason=str(exc) or exc.__class__.__name__,
                debug_metadata=debug_plan,
            )
        citations = build_evidence_citations(evidence)
        if not evidence:
            return CompanionKnowledgeGrounding(
                tool_context="No relevant knowledge evidence was found. Answer generally if possible and do not cite a source.",
                fallback_reason="no_relevant_evidence",
                debug_metadata=debug_plan,
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
                **debug_plan,
                "retrieval_spans": [item.metadata["retrieval_span"] for item in retrievals
                                    if "retrieval_span" in item.metadata],
                "stage_timings": [item.metadata.get("stage_timings", {}) for item in retrievals],
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
                "evidence_status": "relevant_insufficient" if bounded_evidence else "absent",
                "evidence_status_reason": "claim_verification_required" if bounded_evidence else "no_evidence",
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
        filesystem_workspace_files: object = (),
        skill_context: str = "",
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
        workspace_files: list[dict[str, str | int]] = []
        if isinstance(filesystem_workspace_files, (list, tuple)):
            for item in filesystem_workspace_files[:64]:
                if not isinstance(item, dict):
                    continue
                relative_path = str(item.get("relative_path", "") or "").strip().replace("\\", "/")
                parts = relative_path.split("/")
                if (
                    not relative_path
                    or len(relative_path) > 512
                    or relative_path.startswith("/")
                    or ":" in parts[0]
                    or any(part in {"", ".", ".."} for part in parts)
                ):
                    continue
                try:
                    size_bytes = max(0, int(item.get("size_bytes", 0) or 0))
                except (TypeError, ValueError):
                    continue
                workspace_files.append(
                    {"relative_path": relative_path, "size_bytes": size_bytes}
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
            filesystem_workspace_files=tuple(workspace_files),
            skill_context=skill_context,
        )

    def _skill_session(self, payload):
        existing = payload.pop("skill_session", None)
        if existing is not None:
            return existing
        if self._skill_runtime_factory is None:
            return None
        return self._skill_runtime_factory().start(
            str(payload.get("user_message", "")),
            str(payload.get("context_mode", "general") or "general"),
        )

    def send(self, **kwargs: Any) -> CompanionChatResult:
        payload = dict(kwargs)
        shared_skills = payload.pop("skill_session", None)
        phase_callback = payload.pop("phase_callback", None)
        prepared_callback = payload.pop("prepared_callback", None)
        verification_callback = payload.pop("verification_callback", None)
        trace_id = payload.pop("trace_id", None)
        raw_policy = payload.pop("knowledge_access_policy", None)
        raw_legacy_enabled = payload.pop("knowledge_enabled", None)
        policy = self._resolve_knowledge_policy(raw_policy, raw_legacy_enabled)
        raw_document_ids = payload.pop("knowledge_document_ids", ())
        document_ids = tuple(str(item) for item in raw_document_ids)
        history = tuple(payload.get("history", ()) or ())
        if self.function_calling_enabled:
            parts: list[str] = []
            native_prepared: list[CompanionPreparedExecution] = []

            def capture_prepared(value):
                native_prepared.append(value)
                if callable(prepared_callback):
                    prepared_callback(value)

            parts.extend(self.run_functions(
                **payload, knowledge_access_policy=policy,
                skill_session=shared_skills,
                knowledge_document_ids=document_ids, trace_id=trace_id,
                phase_callback=phase_callback, prepared_callback=capture_prepared,
                reset_output=parts.clear, stream=False,
            ))
            prepared = native_prepared[-1]
            native_output = "".join(parts)
        else:
            prepared = self.prepare_execution(
                query=str(payload.get("user_message", "")),
                knowledge_access_policy=policy,
                knowledge_enabled=raw_legacy_enabled,
                document_ids=document_ids,
                history=history,
                context_mode=str(payload.get("context_mode", "general") or "general"),
                source_text=str(payload.get("source_text", "") or ""),
                phase_callback=phase_callback,
                trace_id=trace_id,
            )
        if prepared.tool_name:
            payload["tool_name"] = prepared.tool_name
            payload["tool_context"] = prepared.tool_context
        if not self.function_calling_enabled:
            if shared_skills is not None:
                payload["skill_session"] = shared_skills
            skills = self._skill_session(payload)
            if skills is not None:
                payload["skill_context"] = skills.context()
                prepared = replace(prepared, grounding=replace(prepared.grounding,
                    debug_metadata=dict(prepared.grounding.debug_metadata or {}, skills=skills.snapshot())))
        if not self.function_calling_enabled and callable(prepared_callback):
            prepared_callback(prepared)
        request = self._build_request(**self._with_resolved_reading(payload))
        if callable(phase_callback):
            phase_callback("generating", prepared.plan)
        if self.function_calling_enabled:
            result = SimpleNamespace(session_id=request.session_id,
                user_message=request.user_message, output_text=native_output,
                provider=self.provider_name, model=self.model, request_id=request.request_id)
        elif prepared.direct_output_text:
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
        output_text = result.output_text
        fallback_reason = grounding.fallback_reason
        if prepared.plan.grounding_policy is GroundingPolicy.EVIDENCE:
            from backend.services.grounded_synthesis_service import (
                PARTIAL_GROUNDING_NOTICE,
                evidence_only_grounding_fallback,
            )

            if callable(phase_callback):
                phase_callback("verifying", prepared.plan)
            verification = AgentClaimEvidenceVerifier().verify(
                output_text=output_text, evidence=grounding.evidence, citations=grounding.citations,
            )
            if verification.partial_grounding and "cross_language_support_unscored" in verification.reason_codes:
                output_text = f"{output_text.rstrip()}\n\n{PARTIAL_GROUNDING_NOTICE}"
            elif not verification.passed:
                self._mark_grounding_fallback(grounding)
                output_text = evidence_only_grounding_fallback(
                    evidence=list(grounding.evidence), citations=list(grounding.citations),
                )
                output_text = self._knowledge_failure_text(grounding) or output_text
                fallback_reason = "; ".join(filter(None, (fallback_reason,
                    "grounding_verification_failed:", ",".join(verification.reason_codes))))
            if callable(verification_callback):
                verification_callback(asdict(verification), not verification.passed)
        output_text = self._function_outcome_text(output_text, grounding)
        return CompanionChatResult(
            session_id=result.session_id,
            user_message=result.user_message,
            output_text=output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            knowledge_enabled=bool(raw_legacy_enabled),
            knowledge_access_policy=prepared.knowledge_policy,
            knowledge_decision=prepared.knowledge_decision,
            knowledge_retrieved=prepared.plan.use_knowledge,
            knowledge_document_count=max(self._grounding_document_count(grounding), prepared.catalog_document_count),
            knowledge_chunk_count=self._grounding_chunk_count(grounding),
            knowledge_fallback_reason=fallback_reason,
            evidence=grounding.evidence,
            citations=grounding.citations,
            knowledge_recovery=(grounding.debug_metadata or {}).get("knowledge_recovery", {}),
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
        payload = dict(kwargs)
        skills = self._skill_session(payload)
        if skills is not None:
            payload["skill_context"] = skills.context()
        request = self._build_request(**self._with_resolved_reading(payload))
        yield from self._ensure_stream_service().stream(request)

    @staticmethod
    def _function_prepared(state: KnowledgeFunctionState) -> CompanionPreparedExecution:
        route = (
            (
                CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH
                if state.scope.document_ids
                else CompanionQueryRoute.KNOWLEDGE_SEARCH
            )
            if state.searched
            else (
                CompanionQueryRoute.KNOWLEDGE_CATALOG
                if state.catalog_used
                else CompanionQueryRoute.GENERAL
            )
        )
        policy = (
            GroundingPolicy.EVIDENCE
            if state.searched
            else (GroundingPolicy.MANIFEST if state.catalog_used else GroundingPolicy.NONE)
        )
        if state.recovery.get("reason") in {"document_selection_required", "policy_never"}:
            policy = GroundingPolicy.NONE
        elif any(c.get("status") == "scope_denied" for c in state.calls):
            policy = GroundingPolicy.EVIDENCE
        plan = CompanionExecutionPlan(
            route=route,
            grounding_policy=policy,
            use_knowledge=state.searched,
            document_ids=state.scope.document_ids,
            reason="LLM native function calling",
        )
        reason = (
            "knowledge_request"
            if state.searched
            else ("catalog_request" if state.catalog_used else "current_context_sufficient")
        )
        if state.policy is KnowledgeAccessPolicy.NEVER:
            reason = "explicit_never"
        decision = KnowledgeAccessDecision(
            mode=state.policy,
            should_retrieve=state.searched,
            reason_code=reason,
            scope_strategy=state.scope.strategy,
            query=state.query,
        )
        metadata = {
            "trace_id": state.trace_id,
            "function_calls": list(state.calls),
            "observability": list(state.observability),
            "knowledge_recovery": deepcopy(state.recovery),
            "selected_chunks": [
                {
                    "document_id": item.source_id,
                    "chunk_id": item.metadata.get("chunk_id", ""),
                }
                for item in state.evidence
            ],
        }
        return CompanionPreparedExecution(
            plan=plan,
            knowledge_policy=state.policy,
            knowledge_decision=decision,
            catalog_document_count=state.catalog_count,
            grounding=CompanionKnowledgeGrounding(
                evidence=tuple(state.evidence),
                citations=tuple(state.citations),
                fallback_reason=state.fallback_reason,
                debug_metadata=metadata,
            ),
        )

    def run_functions(
        self,
        *,
        phase_callback=None,
        prepared_callback=None,
        reset_output=None,
        trace_id=None,
        cancel_event: Event | None = None,
        stream=True,
        **kwargs,
    ) -> Iterator[str]:
        payload = dict(kwargs)
        policy = self._resolve_knowledge_policy(
            payload.pop("knowledge_access_policy", None),
            payload.pop("knowledge_enabled", None),
        )
        document_ids = tuple(payload.pop("knowledge_document_ids", ()) or ())
        payload = self._with_resolved_reading(payload)
        if (
            policy is not KnowledgeAccessPolicy.NEVER
            and not document_ids
            and payload.get("source_kind") == "knowledge_document"
        ):
            # The reading document stays a closed scope even when an older client
            # supplies only its source URI rather than its ID.
            library = self._ensure_knowledge_library_service()
            records = library.list_documents() if library is not None else ()
            document_ids = tuple(
                record.document_id
                for record in records
                if record.source_uri == payload.get("resource_url")
            ) or ("__unresolved_reading_document__",)
        scope = KnowledgeScopeResolver().resolve(
            context_mode=payload.get("context_mode", "general"),
            explicit_document_ids=document_ids,
            global_allowed=not document_ids,
        )
        from backend.services.knowledge_function_recovery import wants_full_read
        raw_query = str(payload.get("user_message", ""))
        full_read_requested = wants_full_read(raw_query)
        original_query = raw_query
        if full_read_requested:
            previous_questions = [content for role, content in (payload.get("history", ()) or ()) if role == "user" and content]
            if previous_questions:
                original_query += "\n前一用户问题：" + previous_questions[-1][:4000]
        state = KnowledgeFunctionState(
            scope=scope, policy=policy, trace_id=trace_id or f"companion_{uuid4().hex[:20]}",
            original_query=original_query, full_read_requested=full_read_requested,
        )
        skills = self._skill_session(payload)
        request = self._build_request(**payload)
        messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT + KNOWLEDGE_FUNCTION_PROMPT},
            {"role": "user", "content": build_chat_prompt(request)},
        ]
        messages[0]["content"] += (
            f"\nKnowledge policy: {policy.value}. Permitted document IDs: {list(scope.document_ids)}."
        )
        client = getattr(self._ensure_text_service().provider, "client", None)
        method = "stream_tools" if stream else "complete_tools"
        if not callable(getattr(client, method, None)):
            raise AIConfigurationError(
                "The selected chat provider does not support native function calling."
            )

        def tools_factory():
            if self._knowledge_tools_factory is not None:
                return self._knowledge_tools_factory()
            retrieval = self._ensure_retrieval_service()
            return KnowledgeAgentTools(
                retrieval_service=retrieval,
                chunk_store=getattr(retrieval, "_sparse", None),
                jit_search_read_enabled=True,
                library_service=self._ensure_knowledge_library_service(),
            )

        def on_state(current):
            prepared = self._function_prepared(current)
            if skills is not None:
                prepared.grounding.debug_metadata["skills"] = skills.snapshot()
            if callable(prepared_callback):
                prepared_callback(prepared)

        def on_phase(phase):
            if callable(phase_callback):
                phase_callback(phase, self._function_prepared(state).plan)

        if skills is not None:
            from backend.services.skill_function_bridge import SkillCallingClient
            client = SkillCallingClient(client, skills, on_change=lambda: on_state(state), cancel_event=cancel_event)

        try:
            yield from run_knowledge_functions(
                client=client, messages=messages, state=state, tools_factory=tools_factory,
                request_id=request.request_id, stream=stream, on_state=on_state,
                reset_output=reset_output or (lambda: None), cancel_event=cancel_event, on_phase=on_phase,
            )
        except AgentBudgetExceededError as exc:
            raise AITimeoutError("Local knowledge function calling exceeded its execution deadline.") from exc

    @staticmethod
    def _mark_grounding_fallback(grounding: CompanionKnowledgeGrounding | None) -> None:
        recovery = (grounding.debug_metadata or {}).get("knowledge_recovery", {}) if grounding else {}
        if recovery.get("outcome") in {"normal", "repaired", "recovering"}:
            recovery.update(outcome="fallback", reason="grounding_verification_failed")

    @staticmethod
    def _function_outcome_text(text: str, grounding: CompanionKnowledgeGrounding | None) -> str:
        """Append a server-owned coverage notice after the citation release check."""
        recovery = (grounding.debug_metadata or {}).get("knowledge_recovery", {}) if grounding else {}
        coverage = recovery.get("full_read")
        if not coverage:
            return text or "本次未能生成有效回答，请重试。"
        processed, total = coverage.get("processed_chunks", 0), coverage.get("total_chunks", 0)
        if coverage.get("complete"):
            notice = f"读取范围：当前索引的全部可用正文（{processed}/{total} 个文本片段）。图片、扫描页及未解析内容不在此完成标记内。"
        else:
            notice = f"全文读取尚未完成：已处理 {processed}/{total} 个文本片段。以上内容不能视为对全文的完整结论。"
        return f"{text.rstrip()}\n\n{notice}"

    @staticmethod
    def _knowledge_failure_text(grounding: CompanionKnowledgeGrounding | None) -> str:
        if grounding is None or grounding.evidence:
            return ""
        statuses = {
            item.get("status")
            for item in (grounding.debug_metadata or {}).get("function_calls", [])
        }
        if "tool_timeout" in statuses:
            return "本地资料访问超时，暂时无法核验答案，请稍后重试。"
        if "tool_unavailable" in statuses:
            return "本地资料服务当前不可用，暂时无法核验答案，请检查服务状态后重试。"
        if "scope_denied" in statuses:
            return "请求的资料超出允许范围，或片段尚未通过检索定位，无法核验答案。"
        return ""

    def close(self) -> None:
        service = self._text_service
        self._stream_service = None
        self._chat_service = None
        self._text_service = None
        if service is not None:
            service.close()
