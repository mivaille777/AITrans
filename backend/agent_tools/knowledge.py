from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, Field

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    EmptyToolArgs,
    TypedAgentToolDefinition,
    typed_tool_definition,
)
from backend.knowledge.domain import KnowledgeItem, KnowledgeItemType, KnowledgeRelationOrigin
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.citation_service import build_evidence_citations
from backend.rag.evidence_builder import build_agent_evidence
from backend.rag.models import RetrievalCandidate
from backend.rag.observability import RagTraceEventData, build_rag_trace_events
from backend.rag.query_planner import RagQueryPlan, merge_query_results
from backend.rag.stores.base import VectorSearchFilter


class KnowledgeSearchArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    document_scope: str = Field(default="", max_length=8_000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=50)


class KnowledgeSearchPlannerArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    document_scope: str = Field(default="", max_length=8_000)


class KnowledgeSearchResultItem(AgentToolModel):
    chunk_id: str
    document_id: str
    text: str
    title: str = ""
    source_uri: str = ""
    section_heading: str = ""
    page_number: int | None = Field(default=None, ge=1)
    rank: int | None = Field(default=None, ge=1)
    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResultData(AgentToolModel):
    query: str
    retrieval_strategy: str
    results: list[KnowledgeSearchResultItem] = Field(default_factory=list)
    elapsed_ms: float = Field(ge=0.0)
    fallback_reason: str = ""
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)
    query_plan: RagQueryPlan | None = None
    observability: list[RagTraceEventData] = Field(default_factory=list)


class KnowledgeSaveResultData(AgentToolModel):
    item_id: str
    relation_id: str
    item_type: str
    source_item_id: str
    operation: str


_WRITABLE_KNOWLEDGE_TYPES = frozenset(
    {
        KnowledgeItemType.NOTE,
        KnowledgeItemType.CONCEPT,
        KnowledgeItemType.HIGHLIGHT,
        KnowledgeItemType.EVIDENCE,
        KnowledgeItemType.INSIGHT,
        KnowledgeItemType.QUESTION,
    }
)
_OPERATION_TITLE = {
    "summarize": "Summary",
    "explain": "Explanation",
    "translate": "Translation",
    "generate_notes": "Notes",
    "research": "Research insight",
    "question": "Question",
}
_GROUNDING_METADATA_KEYS = (
    "document_id",
    "section_id",
    "section_heading",
    "page_start",
    "page_end",
    "context_before",
    "context_after",
)


def _document_ids(args: KnowledgeSearchArgs) -> list[str]:
    scoped = args.document_scope.replace("\n", ",").split(",")
    candidates = [*args.document_ids, *scoped]
    normalized: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        document_id = str(value or "").strip()
        if document_id and document_id not in seen:
            normalized.append(document_id)
            seen.add(document_id)
    return normalized


def _result_item(candidate: RetrievalCandidate) -> dict[str, Any]:
    chunk = candidate.chunk
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "text": chunk.text,
        "title": chunk.title,
        "source_uri": chunk.source_uri,
        "section_heading": chunk.section_heading,
        "page_number": chunk.page_number,
        "rank": candidate.rank,
        "dense_score": candidate.dense_score,
        "sparse_score": candidate.sparse_score,
        "fusion_score": candidate.fusion_score,
        "rerank_score": candidate.rerank_score,
        "metadata": dict(candidate.metadata),
    }


def _grounding_metadata(source: KnowledgeItem) -> dict[str, Any]:
    raw = source.metadata if isinstance(source.metadata, dict) else {}
    grounding: dict[str, Any] = {}
    for key in _GROUNDING_METADATA_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                grounding[key] = normalized
        elif key in {"page_start", "page_end"} and isinstance(value, int):
            grounding[key] = value

    resource_document_id = (source.resource_document_id or "").strip()
    if resource_document_id:
        grounding["document_id"] = resource_document_id
    return grounding


def _source_refs(source: KnowledgeItem) -> list[dict[str, Any]]:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    raw_sources = metadata.get("sources")
    sources = [dict(item) for item in raw_sources if isinstance(item, dict)] if isinstance(raw_sources, list) else []
    grounding = _grounding_metadata(source)
    document_id = str(grounding.get("document_id", "")).strip()
    if document_id and not any(str(item.get("document_id", "")).strip() == document_id for item in sources):
        reference: dict[str, Any] = {
            "document_id": document_id,
            "source_uri": source.source_uri,
        }
        section_heading = grounding.get("section_heading")
        if section_heading:
            reference["section"] = section_heading
        page = grounding.get("page_start")
        if isinstance(page, int):
            reference["page"] = page
        sources.append(reference)
    return sources[:64]


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return str(values[0] if values else "").strip()


def _writeback_intent(context: AgentToolInvocationContext) -> tuple[str, str, str, str]:
    source_item_id = context.knowledge_item_id.strip()
    item_type = context.knowledge_writeback_type.strip()
    operation = context.knowledge_writeback_operation.strip()
    relation_type = context.knowledge_relation_type.strip()

    parsed = urlparse(context.resource_url)
    if parsed.scheme == "knowledge-item":
        if not source_item_id:
            source_item_id = unquote(parsed.netloc or parsed.path.lstrip("/"))
        query = parse_qs(parsed.query, keep_blank_values=False)
        item_type = item_type or _first_query_value(query, "type")
        operation = operation or _first_query_value(query, "operation")
        relation_type = relation_type or _first_query_value(query, "relation")

    return (
        source_item_id,
        item_type or KnowledgeItemType.NOTE.value,
        operation or "agent_writeback",
        relation_type or "derived_from",
    )


class KnowledgeAgentTools:
    """Agent-facing boundary over retrieval and confirmed canonical write-back."""

    def __init__(
        self,
        *,
        retrieval_service: Any | None,
        query_planner: Any | None = None,
        workspace_service: KnowledgeWorkspaceService | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._query_planner = query_planner
        self._workspace_service = workspace_service

    def search_knowledge_base(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(KnowledgeSearchArgs, args)
        if self._retrieval_service is None:
            raise RuntimeError("Knowledge retrieval service is unavailable.")

        document_ids = _document_ids(typed)
        filters = (
            VectorSearchFilter(document_ids=document_ids) if document_ids else None
        )
        plan = (
            self._query_planner.plan(typed.query)
            if self._query_planner is not None
            else RagQueryPlan(
                original_query=typed.query,
                rewritten_query=typed.query,
                subqueries=[],
            )
        )
        retrievals = []
        retrieval_errors: list[str] = []
        for retrieval_query in plan.retrieval_queries:
            try:
                retrievals.append(
                    self._retrieval_service.retrieve(
                        retrieval_query,
                        filters=filters,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - degrade per subquery
                retrieval_errors.append(str(exc) or exc.__class__.__name__)
        if not retrievals:
            detail = "; ".join(retrieval_errors) or "retrieval unavailable"
            raise RuntimeError(f"Knowledge retrieval failed: {detail}")
        default_limit = max((len(item.candidates) for item in retrievals), default=1)
        retrieval = merge_query_results(
            typed.query,
            retrievals,
            limit=typed.top_k or default_limit,
        )
        if retrieval_errors:
            retrieval.metadata["subquery_errors"] = retrieval_errors

        candidates = retrieval.candidates
        limited_retrieval = retrieval.model_copy(update={"candidates": candidates})
        evidence = build_agent_evidence(limited_retrieval)
        citations = build_evidence_citations(evidence)
        observability = build_rag_trace_events(
            plan=plan,
            retrievals=retrievals,
            merged=retrieval,
            evidence=evidence,
        )
        results = [_result_item(candidate) for candidate in candidates]
        fallback_reason = str(
            retrieval.metadata.get("fallback_reason")
            or retrieval.metadata.get("reranker_fallback_reason")
            or ""
        )
        if results:
            output_text = "Knowledge search results:\n" + "\n".join(
                f"- {item['title'] or item['document_id']}: {item['text']}"
                for item in results
            )
        else:
            output_text = "No matching knowledge found."
        return AgentToolExecutionResult(
            tool_name="search_knowledge_base",
            output_text=output_text,
            effect="read",
            request_id=context.request_id,
            data={
                "query": retrieval.query,
                "retrieval_strategy": retrieval.retrieval_strategy,
                "results": results,
                "elapsed_ms": retrieval.elapsed_ms,
                "fallback_reason": fallback_reason,
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "citations": [item.model_dump(mode="json") for item in citations],
                "query_plan": plan.model_dump(mode="json"),
                "observability": [
                    event.model_dump(mode="json") for event in observability
                ],
            },
        )

    def save_knowledge_card(
        self,
        context: AgentToolInvocationContext,
        _: BaseModel,
    ) -> AgentToolExecutionResult:
        service = self._workspace_service
        if service is None:
            raise RuntimeError("Knowledge workspace service is unavailable.")

        source_item_id, raw_item_type, operation, relation_type = _writeback_intent(context)
        if not source_item_id:
            raise ValueError("Knowledge write-back requires a trusted source card id.")
        source = service.get_item(source_item_id)
        if source is None:
            raise ValueError("Knowledge write-back source card no longer exists.")

        try:
            item_type = KnowledgeItemType(raw_item_type)
        except ValueError as exc:
            raise ValueError("Knowledge write-back has an invalid target card type.") from exc
        if item_type not in _WRITABLE_KNOWLEDGE_TYPES:
            raise ValueError("Agent write-back cannot create a resource-backed knowledge item.")

        content = context.ai_content.strip() or context.translated_text.strip() or context.source_text.strip()
        if not content:
            raise ValueError("Knowledge write-back has no Agent result to persist.")
        content = content[:50_000]
        title_prefix = _OPERATION_TITLE.get(operation, item_type.value.replace("_", " ").title())
        title = f"{title_prefix} · {source.title}"[:1000]
        provenance = {
            "created_by": "agent",
            "agent_name": "knowledge_agent",
            "run_id": context.run_id,
            "operation": operation,
        }
        grounding = _grounding_metadata(source)
        metadata: dict[str, Any] = {
            "provenance": provenance,
            "source_item_id": source.item_id,
            "source_item_type": source.item_type.value,
            **grounding,
        }
        sources = _source_refs(source)
        if sources:
            metadata["sources"] = sources

        card = service.create_item(
            item_type=item_type,
            title=title,
            summary=content,
            resource_document_id=str(grounding.get("document_id", "")).strip() or None,
            source_uri=source.source_uri,
            metadata=metadata,
        )
        try:
            relation = service.create_relation(
                source_item_id=card.item_id,
                target_item_id=source.item_id,
                relation_type=relation_type,
                label=f"Agent {operation.replace('_', ' ')}",
                origin=KnowledgeRelationOrigin.AI,
                metadata={"provenance": provenance},
            )
        except Exception:
            service.delete_item(card.item_id)
            raise

        return AgentToolExecutionResult(
            tool_name="save_knowledge_card",
            output_text=f"Saved {item_type.value} to Knowledge: {title}",
            effect="write",
            request_id=context.request_id,
            data={
                "item_id": card.item_id,
                "relation_id": relation.relation_id,
                "item_type": item_type.value,
                "source_item_id": source.item_id,
                "operation": operation,
            },
        )


def build_knowledge_tool_definitions(
    tools: KnowledgeAgentTools,
) -> tuple[TypedAgentToolDefinition, ...]:
    return (
        typed_tool_definition(
            name="search_knowledge_base",
            title="Search knowledge base",
            description="Search indexed local documents with hybrid dense and sparse retrieval.",
            category="knowledge",
            effect="read",
            requires_reading_context=False,
            requires_confirmation=False,
            args_model=KnowledgeSearchArgs,
            result_model=KnowledgeSearchResultData,
            executor=tools.search_knowledge_base,
            planner_args_model=KnowledgeSearchPlannerArgs,
            retry_policy="safe",
        ),
        typed_tool_definition(
            name="save_knowledge_card",
            title="Save result to Knowledge",
            description=(
                "Persist the already-produced Agent result as a derived canonical Knowledge card. "
                "Use only when the user explicitly asks to save a result to the Knowledge Library; "
                "the runtime supplies the source card, target card type, operation, and relation."
            ),
            category="knowledge",
            effect="write",
            requires_reading_context=False,
            requires_confirmation=True,
            args_model=EmptyToolArgs,
            result_model=KnowledgeSaveResultData,
            executor=tools.save_knowledge_card,
            planner_args_model=EmptyToolArgs,
            retry_policy="never",
        ),
    )


__all__ = [
    "KnowledgeAgentTools",
    "KnowledgeSaveResultData",
    "KnowledgeSearchArgs",
    "KnowledgeSearchPlannerArgs",
    "KnowledgeSearchResultData",
    "KnowledgeSearchResultItem",
    "build_knowledge_tool_definitions",
]
