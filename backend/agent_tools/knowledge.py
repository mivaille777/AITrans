from __future__ import annotations

from typing import Any, Protocol, cast
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
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult
from backend.rag.observability import RagTraceEventData, build_rag_trace_events
from backend.rag.query_planner import RagQueryPlan, merge_query_results
from backend.rag.stores.base import VectorSearchFilter


class KnowledgeSearchArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    document_scope: str = Field(default="", max_length=8_000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=50)


class KnowledgeReadChunkArgs(AgentToolModel):
    chunk_id: str = Field(min_length=1, max_length=256)


class KnowledgeReadSectionArgs(AgentToolModel):
    chunk_id: str = Field(min_length=1, max_length=256)
    neighbor_radius: int = Field(default=1, ge=0, le=2)


class KnowledgeSearchPlannerArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    document_scope: str = Field(default="", max_length=8_000)


class KnowledgeSearchResultItem(AgentToolModel):
    chunk_id: str
    document_id: str
    title: str = ""
    section_heading: str = ""
    page_number: int | None = Field(default=None, ge=1)
    rank: int | None = Field(default=None, ge=1)
    snippet: str | None = None
    text: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None


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


class KnowledgeReadResultItem(AgentToolModel):
    chunk_id: str
    document_id: str
    text: str
    title: str = ""
    section_heading: str = ""
    section_path: list[str] = Field(default_factory=list)
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int = Field(ge=0)


class KnowledgeReadResultData(AgentToolModel):
    anchor_chunk_id: str
    neighbor_radius: int = Field(default=0, ge=0, le=2)
    chunks: list[KnowledgeReadResultItem] = Field(default_factory=list)
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)
    duplicate_read: bool = False
    duplicate_evidence_count: int = Field(default=0, ge=0)


class KnowledgeChunkStore(Protocol):
    """Minimal public read interface implemented by the sparse chunk catalogue."""

    def get_chunk(self, chunk_id: str) -> DocumentChunk | None: ...

    def section_neighbors(
        self,
        anchor: DocumentChunk,
        radius: int,
    ) -> list[DocumentChunk]: ...


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


def _candidate_snippet(candidate: RetrievalCandidate, max_chars: int = 320) -> str:
    """Return a bounded navigational excerpt without modifying stored evidence."""

    limit = max(0, int(max_chars))
    prefix = candidate.chunk.text[:limit]
    return " ".join(prefix.split())[:limit]


def _result_item(candidate: RetrievalCandidate) -> dict[str, Any]:
    chunk = candidate.chunk
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "section_heading": chunk.section_heading,
        "page_number": chunk.page_number,
        "rank": candidate.rank,
        "snippet": _candidate_snippet(candidate),
        "dense_score": candidate.dense_score,
        "sparse_score": candidate.sparse_score,
        "fusion_score": candidate.fusion_score,
        "rerank_score": candidate.rerank_score,
    }


def _legacy_result_item(candidate: RetrievalCandidate) -> dict[str, Any]:
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


def _validate_chunk_scope(
    chunk: DocumentChunk,
    context: AgentToolInvocationContext,
) -> None:
    allowed_document_ids = {
        str(item or "").strip()
        for item in context.knowledge_document_ids
        if str(item or "").strip()
    }
    if allowed_document_ids:
        if chunk.document_id not in allowed_document_ids:
            raise PermissionError("Knowledge chunk is outside the allowed document scope.")
        return
    if not context.knowledge_scope_allow_global:
        raise PermissionError("Knowledge access requires an explicit document scope.")


def _read_item(chunk: DocumentChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "text": chunk.text,
        "title": chunk.title,
        "section_heading": chunk.section_heading,
        "section_path": list(chunk.section_path),
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
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
        chunk_store: KnowledgeChunkStore | None = None,
        jit_search_read_enabled: bool = False,
        workspace_service: KnowledgeWorkspaceService | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._query_planner = query_planner
        self._chunk_store = chunk_store
        self.jit_search_read_enabled = bool(jit_search_read_enabled)
        self._workspace_service = workspace_service

    def search_knowledge_base(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(KnowledgeSearchArgs, args)
        if self._retrieval_service is None:
            raise RuntimeError("Knowledge retrieval service is unavailable.")

        requested_document_ids = _document_ids(typed)
        allowed_document_ids = list(
            dict.fromkeys(
                str(item or "").strip()
                for item in context.knowledge_document_ids
                if str(item or "").strip()
            )
        )
        if allowed_document_ids:
            if requested_document_ids:
                out_of_scope = set(requested_document_ids) - set(allowed_document_ids)
                if out_of_scope:
                    raise PermissionError(
                        "Knowledge search requested a document outside the allowed scope."
                    )
                document_ids = requested_document_ids
            else:
                document_ids = allowed_document_ids
        elif context.knowledge_scope_allow_global:
            document_ids = requested_document_ids
        else:
            raise PermissionError("Knowledge search requires an explicit document scope.")
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
        for candidate in candidates:
            _validate_chunk_scope(candidate.chunk, context)
        evidence = (
            []
            if self.jit_search_read_enabled
            else build_agent_evidence(retrieval)
        )
        citations = build_evidence_citations(evidence)
        observability = build_rag_trace_events(
            plan=plan,
            retrievals=retrievals,
            merged=retrieval,
            evidence=evidence,
        )
        result_builder = (
            _result_item if self.jit_search_read_enabled else _legacy_result_item
        )
        results = [result_builder(candidate) for candidate in candidates]
        fallback_reason = str(
            retrieval.metadata.get("fallback_reason")
            or retrieval.metadata.get("reranker_fallback_reason")
            or ""
        )
        if results:
            text_key = "snippet" if self.jit_search_read_enabled else "text"
            output_text = "Knowledge search results:\n" + "\n".join(
                f"- {item['title'] or item['document_id']}: {item[text_key]}"
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

    def _read_chunks(
        self,
        context: AgentToolInvocationContext,
        *,
        tool_name: str,
        anchor_chunk_id: str,
        chunks: list[DocumentChunk],
        neighbor_radius: int,
    ) -> AgentToolExecutionResult:
        if not chunks:
            raise LookupError("Knowledge chunk no longer exists.")
        candidates: list[RetrievalCandidate] = []
        seen_chunk_ids: set[str] = set()
        for rank, chunk in enumerate(chunks, start=1):
            _validate_chunk_scope(chunk, context)
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    rank=rank,
                    metadata={
                        "jit_read": True,
                        "read_anchor_chunk_id": anchor_chunk_id,
                        "neighbor_radius": neighbor_radius,
                    },
                )
            )
        if not candidates:
            raise LookupError("Knowledge chunk no longer exists.")

        retrieval = RetrievalResult(
            query=f"read:{anchor_chunk_id}",
            candidates=candidates,
            retrieval_strategy="jit_read",
        )
        evidence = build_agent_evidence(retrieval)
        citations = build_evidence_citations(evidence)
        output_text = "\n\n".join(
            f"[{item.chunk.chunk_id}] {item.chunk.text}" for item in candidates
        )
        return AgentToolExecutionResult(
            tool_name=tool_name,
            output_text=output_text,
            effect="read",
            request_id=context.request_id,
            data={
                "anchor_chunk_id": anchor_chunk_id,
                "neighbor_radius": neighbor_radius,
                "chunks": [_read_item(item.chunk) for item in candidates],
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "citations": [item.model_dump(mode="json") for item in citations],
                "duplicate_read": False,
                "duplicate_evidence_count": 0,
            },
        )

    def read_knowledge_chunk(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(KnowledgeReadChunkArgs, args)
        if self._chunk_store is None:
            raise RuntimeError("Knowledge chunk store is unavailable.")
        chunk = self._chunk_store.get_chunk(typed.chunk_id)
        if chunk is None:
            raise LookupError("Knowledge chunk no longer exists.")
        _validate_chunk_scope(chunk, context)
        return self._read_chunks(
            context,
            tool_name="read_knowledge_chunk",
            anchor_chunk_id=chunk.chunk_id,
            chunks=[chunk],
            neighbor_radius=0,
        )

    def read_knowledge_section(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(KnowledgeReadSectionArgs, args)
        if self._chunk_store is None:
            raise RuntimeError("Knowledge chunk store is unavailable.")
        anchor = self._chunk_store.get_chunk(typed.chunk_id)
        if anchor is None:
            raise LookupError("Knowledge chunk no longer exists.")
        _validate_chunk_scope(anchor, context)
        neighbors = self._chunk_store.section_neighbors(
            anchor,
            typed.neighbor_radius,
        )
        if not any(item.chunk_id == anchor.chunk_id for item in neighbors):
            raise RuntimeError("Knowledge chunk store returned a section without its anchor.")
        anchor_section = tuple(anchor.section_path)
        for neighbor in neighbors:
            if (
                neighbor.document_id != anchor.document_id
                or tuple(neighbor.section_path) != anchor_section
            ):
                raise RuntimeError(
                    "Knowledge chunk store returned a chunk outside the anchor section."
                )
        return self._read_chunks(
            context,
            tool_name="read_knowledge_section",
            anchor_chunk_id=anchor.chunk_id,
            chunks=neighbors,
            neighbor_radius=typed.neighbor_radius,
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
            # Derived cards keep document grounding in metadata/sources. The
            # canonical resource_document_id remains reserved for the single
            # resource-backed paper/document card.
            resource_document_id=None,
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
    search_description = (
        "Locate relevant indexed document chunks. Returned snippets are navigation hints, "
        "not evidence; read selected chunks before using them to support an answer."
        if tools.jit_search_read_enabled
        else "Search indexed local documents with hybrid dense and sparse retrieval."
    )
    definitions = [
        typed_tool_definition(
            name="search_knowledge_base",
            title="Search knowledge base",
            description=search_description,
            category="knowledge",
            effect="read",
            requires_reading_context=False,
            requires_confirmation=False,
            args_model=KnowledgeSearchArgs,
            result_model=KnowledgeSearchResultData,
            executor=tools.search_knowledge_base,
            planner_args_model=KnowledgeSearchPlannerArgs,
            retry_policy="safe",
        )
    ]
    if tools.jit_search_read_enabled:
        definitions.extend(
            (
                typed_tool_definition(
                    name="read_knowledge_chunk",
                    title="Read knowledge chunk",
                    description=(
                        "Read the full text of one previously located knowledge chunk. "
                        "Only Read results provide factual evidence and citations."
                    ),
                    category="knowledge",
                    effect="read",
                    requires_reading_context=False,
                    requires_confirmation=False,
                    args_model=KnowledgeReadChunkArgs,
                    result_model=KnowledgeReadResultData,
                    executor=tools.read_knowledge_chunk,
                    retry_policy="safe",
                ),
                typed_tool_definition(
                    name="read_knowledge_section",
                    title="Read knowledge section",
                    description=(
                        "Read one located chunk and bounded neighboring chunks from the same section "
                        "when local context is needed. Only Read results provide factual evidence and citations."
                    ),
                    category="knowledge",
                    effect="read",
                    requires_reading_context=False,
                    requires_confirmation=False,
                    args_model=KnowledgeReadSectionArgs,
                    result_model=KnowledgeReadResultData,
                    executor=tools.read_knowledge_section,
                    retry_policy="safe",
                ),
            )
        )
    definitions.append(
        typed_tool_definition(
            name="save_knowledge_card",
            title="Save result to Knowledge",
            description=(
                "Persist the already-produced Agent result as a derived canonical Knowledge card. "
                "Use only when the user's request requires saving a result to the Knowledge Library; "
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
        )
    )
    return tuple(definitions)


__all__ = [
    "KnowledgeAgentTools",
    "KnowledgeSaveResultData",
    "KnowledgeSearchArgs",
    "KnowledgeSearchPlannerArgs",
    "KnowledgeSearchResultData",
    "KnowledgeSearchResultItem",
    "KnowledgeChunkStore",
    "KnowledgeReadChunkArgs",
    "KnowledgeReadResultData",
    "KnowledgeReadResultItem",
    "KnowledgeReadSectionArgs",
    "build_knowledge_tool_definitions",
]
