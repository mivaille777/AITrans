from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
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
from app.ai.errors import AIConfigurationError
from app.ai.service import AITextService
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
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
from backend.services.reading_context_adapter import to_reading_context


@dataclass(frozen=True, slots=True)
class CompanionKnowledgeGrounding:
    evidence: tuple[AgentEvidenceItem, ...] = ()
    citations: tuple[AgentCitationRef, ...] = ()
    tool_context: str = ""
    fallback_reason: str = ""


@dataclass(frozen=True, slots=True)
class CompanionChatResult:
    session_id: str
    user_message: str
    output_text: str
    provider: str
    model: str
    request_id: int = 0
    knowledge_enabled: bool = False
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
    ) -> None:
        self._text_service = text_service
        self._chat_service = chat_service
        self._stream_service = stream_service
        self._reading_resolver = reading_resolver
        self._retrieval_service = retrieval_service
        self._query_planner = query_planner
        self._grounded_context_builder = GroundedContextBuilder()

    def prepare_knowledge(
        self,
        query: str,
        document_ids: tuple[str, ...] = (),
        *,
        history: tuple[tuple[str, str], ...] = (),
    ) -> CompanionKnowledgeGrounding:
        if self._retrieval_service is None:
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
        plan = (
            self._query_planner.plan(query, history=history)
            if self._query_planner is not None
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
                    self._retrieval_service.retrieve(
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

        resolver = self._reading_resolver
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
        )

    def send(self, **kwargs: Any) -> CompanionChatResult:
        payload = dict(kwargs)
        knowledge_enabled = bool(payload.pop("knowledge_enabled", False))
        raw_document_ids = payload.pop("knowledge_document_ids", ())
        document_ids = tuple(str(item) for item in raw_document_ids)
        history = tuple(payload.get("history", ()) or ())
        grounding = (
            self.prepare_knowledge(
                str(payload.get("user_message", "")),
                document_ids,
                history=history,
            )
            if knowledge_enabled
            else CompanionKnowledgeGrounding()
        )
        if knowledge_enabled:
            payload["tool_name"] = "search_knowledge_base"
            payload["tool_context"] = grounding.tool_context
        request = self._build_request(**self._with_resolved_reading(payload))
        result = self._ensure_chat_service().execute(request)
        return CompanionChatResult(
            session_id=result.session_id,
            user_message=result.user_message,
            output_text=result.output_text,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            knowledge_enabled=knowledge_enabled,
            knowledge_fallback_reason=grounding.fallback_reason,
            evidence=grounding.evidence,
            citations=grounding.citations,
        )

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
