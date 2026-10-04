from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.models.agent_artifacts import EvidenceRef
from backend.models.agent_evidence import (
    EvidenceLocator,
    EvidencePacket,
    EvidenceSourceCategory,
    EvidenceSourceStatus,
)
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.models.agent_tasks import ScopeContext, ScopeMode
from backend.rag.citation_service import build_evidence_citations
from backend.rag.exceptions import RagRetrievalError
from backend.rag.models import RetrievalResult
from backend.rag.observability import build_rag_trace_events, current_rag_trace
from backend.rag.query_planner import RagQueryPlan
from backend.rag.stores.base import VectorSearchFilter

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


def _tokens(value: object) -> set[str]:
    text = " ".join(str(value or "").casefold().split())
    values = set(_TOKEN_RE.findall(text))
    if len(values) <= 1 and any("\u4e00" <= char <= "\u9fff" for char in text):
        compact = "".join(char for char in text if "\u4e00" <= char <= "\u9fff")
        values.update(compact[index : index + 2] for index in range(max(0, len(compact) - 1)))
    return {value for value in values if value}


def _relevance(query: str, text: str) -> float:
    normalized_query = " ".join(query.casefold().split())
    normalized_text = " ".join(text.casefold().split())
    if normalized_query and normalized_query in normalized_text:
        return 1.0
    query_tokens = _tokens(normalized_query)
    if not query_tokens:
        return 0.0
    overlap = query_tokens.intersection(_tokens(normalized_text))
    return len(overlap) / len(query_tokens)


class ScopedEvidenceCache:
    def __init__(self, *, max_entries: int = 128) -> None:
        if max_entries < 1:
            raise ValueError("evidence cache size must be positive")
        self._max_entries = max_entries
        self._values: OrderedDict[str, tuple[EvidencePacket, ...]] = OrderedDict()
        self._retrievals: dict[str, RetrievalResult] = {}
        self._lock = RLock()

    @staticmethod
    def key(
        *,
        scope: ScopeContext,
        query: str,
        limit: int,
        model_version: str,
        filters: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "scope": scope.model_dump(mode="json"),
            "query": " ".join(str(query or "").split()),
            "limit": int(limit),
            "model_version": str(model_version or ""),
            "filters": dict(filters or {}),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def get(self, key: str) -> tuple[EvidencePacket, ...] | None:
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return tuple(item.model_copy(deep=True) for item in value) if value is not None else None

    def get_retrieval(self, key: str) -> RetrievalResult | None:
        with self._lock:
            result = self._retrievals.get(key)
            return result.model_copy(deep=True) if result is not None else None

    def discard(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)
            self._retrievals.pop(key, None)

    def put(
        self, key: str, value: Iterable[EvidencePacket], *, retrieval: RetrievalResult | None = None,
    ) -> tuple[EvidencePacket, ...]:
        stored = tuple(item.model_copy(deep=True) for item in value)
        with self._lock:
            self._values[key] = stored
            self._values.move_to_end(key)
            if retrieval is not None:
                self._retrievals[key] = retrieval.model_copy(deep=True)
            else:
                self._retrievals.pop(key, None)
            while len(self._values) > self._max_entries:
                oldest, _ = self._values.popitem(last=False)
                self._retrievals.pop(oldest, None)
        return tuple(item.model_copy(deep=True) for item in stored)


class ScopedEvidenceService:
    """One scoped evidence entrance over existing RAG, notes, knowledge, and review services."""

    def __init__(
        self,
        *,
        rag_retriever: Any | None = None,
        research_notes: Any | None = None,
        knowledge_workspace: Any | None = None,
        research_memory_reliability: Any | None = None,
        evidence_review: Any | None = None,
        cache: ScopedEvidenceCache | None = None,
        model_version: str = "deterministic-v1",
    ) -> None:
        self._rag = rag_retriever
        self._notes = research_notes
        self._knowledge = knowledge_workspace
        self._reliability = research_memory_reliability
        self._review = evidence_review
        self._cache = cache or ScopedEvidenceCache()
        self._model_version = model_version

    def retrieve(
        self,
        *,
        query: str,
        scope: ScopeContext,
        limit: int,
    ) -> tuple[EvidenceRef, ...]:
        return tuple(packet.evidence_ref for packet in self.retrieve_packets(query=query, scope=scope, limit=limit))

    @staticmethod
    def to_agent_evidence(packets: Iterable[EvidencePacket]) -> tuple[AgentEvidenceItem, ...]:
        return tuple(
            AgentEvidenceItem(
                evidence_id=packet.evidence_ref.evidence_id,
                source_type=packet.evidence_ref.source_type,
                source_id=packet.evidence_ref.source_id,
                title=packet.title,
                resource_url=packet.locator.source_uri,
                location=json.dumps(
                    packet.evidence_ref.locator,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                excerpt=packet.text,
                score=packet.relevance_score,
                metadata={
                    "source_version": packet.evidence_ref.source_version,
                    "source_hash": packet.evidence_ref.source_hash,
                    "source_category": packet.source_category.value,
                    "source_status": packet.status.value,
                    "review_status": packet.review_status,
                    "machine_status": packet.machine_status,
                },
            )
            for packet in packets
        )

    @classmethod
    def build_citations(cls, packets: Iterable[EvidencePacket]) -> tuple[AgentCitationRef, ...]:
        evidence = cls.to_agent_evidence(packets)
        return tuple(build_evidence_citations(evidence))

    def retrieve_packets(
        self,
        *,
        query: str,
        scope: ScopeContext,
        limit: int = 8,
        include_reviewed: bool = True,
    ) -> tuple[EvidencePacket, ...]:
        normalized_query = " ".join(str(query or "").split())
        if not normalized_query:
            raise ValueError("evidence query must not be empty")
        bounded_limit = max(1, min(100, int(limit)))
        if scope.mode is ScopeMode.RESTRICTED and not (
            scope.allowed_document_ids or scope.allowed_note_ids or scope.allowed_item_ids
        ):
            return ()

        packets: list[EvidencePacket] = []
        packets.extend(self._document_packets(normalized_query, scope, bounded_limit))
        packets.extend(self._note_packets(normalized_query, scope, bounded_limit))
        packets.extend(self._knowledge_packets(normalized_query, scope))
        if include_reviewed:
            packets.extend(self._review_packets(normalized_query, scope, bounded_limit))

        deduped: dict[str, EvidencePacket] = {}
        for packet in packets:
            previous = deduped.get(packet.evidence_ref.evidence_id)
            if previous is None or packet.relevance_score > previous.relevance_score:
                deduped[packet.evidence_ref.evidence_id] = packet
        ordered = sorted(
            deduped.values(),
            key=lambda item: (-item.relevance_score, item.evidence_ref.evidence_id),
        )[:bounded_limit]
        return tuple(ordered)

    def _document_packets(self, query: str, scope: ScopeContext, limit: int) -> list[EvidencePacket]:
        if self._rag is None or (
            scope.mode is ScopeMode.RESTRICTED and not scope.allowed_document_ids
        ):
            return []
        started_at, started = datetime.now(UTC), perf_counter()
        parent_trace_id, event_sink = current_rag_trace()
        trace_id = parent_trace_id or f"rag_{uuid4().hex[:20]}"
        filters = VectorSearchFilter(document_ids=list(scope.allowed_document_ids))
        version_getter = getattr(self._rag, "evidence_cache_version", None)
        version = version_getter(filters=filters) if callable(version_getter) else None
        cache_enabled = not callable(version_getter) or version is not None
        cache_key = self._cache.key(
            scope=scope, query=query, limit=limit, model_version=self._model_version,
            filters={"retrieval_version": version},
        )
        validator = getattr(self._rag, "validate_evidence_candidates", None)
        cached = self._cache.get(cache_key) if cache_enabled else None
        if cached is not None:
            cached_result = self._cache.get_retrieval(cache_key)
            if callable(validator):
                try:
                    if cached_result is None:
                        cached = None
                    else:
                        validator(cached_result, filters=filters)
                except RagRetrievalError:
                    cached = None
            if cached is not None and (
                not callable(version_getter) or version_getter(filters=filters) == version
            ):
                if cached_result is not None and (parent_trace_id or callable(event_sink)):
                    previous = cached_result.metadata.get("retrieval_span", {})
                    ended_at = datetime.now(UTC)
                    span = {"trace_id": trace_id, "span_id": f"{trace_id}:cache:{uuid4().hex[:12]}",
                            "parent_id": trace_id, "stage": "cache", "status": "complete",
                            "started_at": started_at.isoformat(), "ended_at": ended_at.isoformat(),
                            "elapsed_ms": (perf_counter() - started) * 1000}
                    cached_result.elapsed_ms = span["elapsed_ms"]
                    cached_result.metadata.update({"retrieval_span": span, "stage_timings": {"cache": span},
                        "evidence_cache_hit": True, "cache_source_span_ids": [previous["span_id"]] if previous else []})
                    self._record_document_trace(query, cached_result, cached, trace_id, event_sink)
                return list(cached)
            self._cache.discard(cache_key)
        result = self._rag.retrieve(
            query,
            filters=filters,
            final_top_k=limit,
            **({"trace_id": trace_id} if callable(validator) else {}),
        )
        if callable(validator):
            validator(result, filters=filters)
        packets: list[EvidencePacket] = []
        allowed = set(scope.allowed_document_ids)
        for candidate in result.candidates:
            chunk = candidate.chunk
            if scope.mode is ScopeMode.RESTRICTED and chunk.document_id not in allowed:
                continue
            score = next(
                (
                    float(value)
                    for value in (candidate.rerank_score, candidate.fusion_score, candidate.sparse_score, candidate.dense_score)
                    if value is not None
                ),
                0.0,
            )
            locator = EvidenceLocator(
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                element_id=str(chunk.metadata.get("element_id", "") or ""),
                table_id=str(chunk.metadata.get("table_id", "") or ""),
                image_id=str(chunk.metadata.get("image_id", "") or ""),
                section_path=list(chunk.section_path),
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                source_uri=chunk.source_uri,
            )
            reference = EvidenceRef(
                evidence_id=f"chunk:{chunk.chunk_id}",
                source_id=chunk.document_id,
                source_type="document_chunk",
                source_version=scope.source_versions.get(chunk.document_id, chunk.document_hash),
                source_hash=chunk.document_hash,
                locator=locator.model_dump(mode="json", exclude_none=True),
            )
            packets.append(
                EvidencePacket(
                    evidence_ref=reference,
                    text=chunk.text,
                    title=chunk.title or chunk.section_heading,
                    source_category=EvidenceSourceCategory.DOCUMENT,
                    status=EvidenceSourceStatus.FRESH,
                    relevance_score=max(0.0, score),
                    locator=locator,
                    metadata={"retrieval_strategy": result.retrieval_strategy},
                )
            )
        self._record_document_trace(query, result, packets, trace_id, event_sink)
        if cache_enabled and (
            not callable(version_getter) or version_getter(filters=filters) == version
        ):
            self._cache.put(cache_key, packets, retrieval=result)
        return packets

    def _record_document_trace(
        self, query: str, result: RetrievalResult, packets: Iterable[EvidencePacket], trace_id: str, event_sink: Any,
    ) -> None:
        if current_rag_trace()[0] or callable(event_sink):
            for packet in packets:
                packet.metadata.update({"retrieval_span": result.metadata.get("retrieval_span"),
                    "stage_timings": result.metadata.get("stage_timings", {}),
                    "evidence_cache_hit": result.metadata.get("evidence_cache_hit", False),
                    "cache_source_span_ids": result.metadata.get("cache_source_span_ids", [])})
        if callable(event_sink):
            from backend.agent_core.events import AgentEventType

            events = build_rag_trace_events(
                plan=RagQueryPlan(original_query=query, rewritten_query=query, subqueries=[]),
                retrievals=[result], merged=result, evidence=self.to_agent_evidence(packets),
                query_id=f"{trace_id}:rag:{uuid4().hex[:12]}", trace_id=trace_id,
            )
            for event in events:
                event_sink(AgentEventType(event.event_type), event.payload)

    def _note_packets(self, query: str, scope: ScopeContext, limit: int) -> list[EvidencePacket]:
        if self._notes is None or (
            scope.mode is ScopeMode.RESTRICTED and not scope.allowed_note_ids
        ):
            return []
        matches = self._notes.search(
            query,
            limit=limit,
            note_ids=list(scope.allowed_note_ids),
        )
        allowed = set(scope.allowed_note_ids)
        packets: list[EvidencePacket] = []
        for match in matches:
            note = match.note
            if scope.mode is ScopeMode.RESTRICTED and note.note_id not in allowed:
                continue
            status_value = "legacy_unknown"
            if self._reliability is not None and scope.workspace_id:
                status_value = str(
                    self._reliability.source_status(
                        workspace_id=scope.workspace_id,
                        note_id=note.note_id,
                    )
                )
            status = EvidenceSourceStatus(status_value)
            if status in {EvidenceSourceStatus.STALE, EvidenceSourceStatus.DETACHED, EvidenceSourceStatus.ORPHANED}:
                continue
            text = "\n".join(
                value
                for value in (note.source_text, note.translated_text, note.ai_content, note.user_note)
                if str(value or "").strip()
            )
            locator = EvidenceLocator(
                source_uri=note.resource_url,
                section_path=[note.section_heading] if note.section_heading else [],
            )
            packets.append(
                EvidencePacket(
                    evidence_ref=EvidenceRef(
                        evidence_id=f"note:{note.note_id}",
                        source_id=note.note_id,
                        source_type="research_note",
                        source_version=scope.source_versions.get(note.note_id, note.fingerprint),
                        source_hash=note.fingerprint,
                        locator=locator.model_dump(mode="json", exclude_none=True),
                    ),
                    text=text,
                    title=note.display_title,
                    source_category=EvidenceSourceCategory.RESEARCH_NOTE,
                    status=status,
                    relevance_score=max(0.0, float(match.score)),
                    locator=locator,
                )
            )
        return packets

    def _knowledge_packets(self, query: str, scope: ScopeContext) -> list[EvidencePacket]:
        if self._knowledge is None or (
            scope.mode is ScopeMode.RESTRICTED and not scope.allowed_item_ids
        ):
            return []
        allowed = set(scope.allowed_item_ids)
        items = (
            [self._knowledge.get_item(item_id) for item_id in sorted(allowed)]
            if scope.mode is ScopeMode.RESTRICTED
            else self._knowledge.list_items()
        )
        relations = self._knowledge.list_relations()
        scoped_relations = [
            relation
            for relation in relations
            if (not allowed or (relation.source_item_id in allowed and relation.target_item_id in allowed))
        ]
        relation_ids_by_item: dict[str, list[str]] = {}
        for relation in scoped_relations:
            relation_ids_by_item.setdefault(relation.source_item_id, []).append(relation.relation_id)
            relation_ids_by_item.setdefault(relation.target_item_id, []).append(relation.relation_id)

        packets: list[EvidencePacket] = []
        for item in items:
            if item is None:
                continue
            text = "\n".join(value for value in (item.title, item.summary) if value)
            score = _relevance(query, text)
            # A graph degree alone is never evidence; relations only annotate a lexical seed.
            if score <= 0:
                continue
            locator = EvidenceLocator(source_uri=item.source_uri)
            packets.append(
                EvidencePacket(
                    evidence_ref=EvidenceRef(
                        evidence_id=f"knowledge:{item.item_id}",
                        source_id=item.item_id,
                        source_type=item.item_type.value,
                        source_version=scope.source_versions.get(item.item_id, item.updated_at.isoformat()),
                        locator=locator.model_dump(mode="json", exclude_none=True),
                    ),
                    text=text,
                    title=item.title,
                    source_category=EvidenceSourceCategory.KNOWLEDGE_ITEM,
                    status=EvidenceSourceStatus.FRESH,
                    relevance_score=score,
                    locator=locator,
                    relation_ids=sorted(relation_ids_by_item.get(item.item_id, [])),
                )
            )
        return packets

    def _review_packets(self, query: str, scope: ScopeContext, limit: int) -> list[EvidencePacket]:
        if self._review is None or not scope.workspace_id:
            return []
        snapshot = self._review.snapshot(workspace_id=scope.workspace_id, query=query, limit=limit)
        allowed_documents = set(scope.allowed_document_ids)
        allowed_notes = set(scope.allowed_note_ids)
        packets: list[EvidencePacket] = []
        for item in snapshot.items:
            if item.review.status != "accepted":
                continue
            if item.ledger.validation.status not in {"supported", "contested"}:
                continue
            if scope.mode is ScopeMode.RESTRICTED:
                links = [
                    link
                    for link in item.ledger.entry.links
                    if link.document_id in allowed_documents
                    and link.note_id in allowed_notes
                ]
            else:
                links = list(item.ledger.entry.links)
            if not links:
                continue
            entry = item.ledger.entry
            packets.append(
                EvidencePacket(
                    evidence_ref=EvidenceRef(
                        evidence_id=f"ledger:{entry.entry_id}",
                        source_id=entry.entry_id,
                        source_type="evidence_ledger",
                        source_version=entry.updated_at,
                        locator={"workspace_id": scope.workspace_id},
                    ),
                    text=entry.statement,
                    title="Reviewed evidence",
                    source_category=EvidenceSourceCategory.REVIEW_LEDGER,
                    status=EvidenceSourceStatus.ACCEPTED,
                    relevance_score=max(0.0, _relevance(query, entry.statement)),
                    review_status=item.review.status,
                    machine_status=item.ledger.validation.status,
                    metadata={"linked_evidence_ids": sorted({link.evidence_id for link in links})},
                )
            )
        return packets


__all__ = ["ScopedEvidenceCache", "ScopedEvidenceService"]
