from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.models.agent_tasks import ScopeContext, ScopeMode


class KnowledgeInjector:
    """Inject Knowledge Runtime outputs into a shared multi-agent context.

    Stage 4's ``AgentKnowledgeRuntime.build_context`` returns an
    ``AgentKnowledgeContext`` dataclass, while tests and future adapters may
    return dictionaries. This adapter deliberately accepts both shapes so the
    multi-agent layer stays decoupled from the concrete knowledge runtime.
    """

    def __init__(self, knowledge_runtime=None, *, evidence_service=None, top_k: int = 5):
        self.knowledge_runtime = knowledge_runtime
        self.evidence_service = evidence_service
        self.top_k = max(1, int(top_k))

    @staticmethod
    def _value(result: Any, key: str, default: Any = None) -> Any:
        if isinstance(result, Mapping):
            return result.get(key, default)
        return getattr(result, key, default)

    @staticmethod
    def _citation_key(citation: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(citation.get("id", "") or ""),
            str(citation.get("title", "") or ""),
            str(citation.get("source_type", "") or ""),
        )

    def inject(self, query: str, context: Any):
        if context is None:
            return context

        runtime = getattr(context, "runtime", {}) or {}
        raw_scope = runtime.get("scope_context")
        scope: ScopeContext | None = None
        if isinstance(raw_scope, ScopeContext):
            scope = raw_scope
        elif isinstance(raw_scope, Mapping):
            scope = ScopeContext.model_validate(raw_scope)

        if self.evidence_service is not None and scope is not None:
            packets = self.evidence_service.retrieve_packets(
                query=query,
                scope=scope,
                limit=self.top_k,
            )
            context.knowledge_context = "\n".join(
                f"[{packet.evidence_ref.evidence_id}] {packet.text}"
                for packet in packets
                if packet.text
            )
            for packet in packets:
                context.add_citation(
                    {
                        "id": packet.evidence_ref.evidence_id,
                        "title": packet.title,
                        "source_type": packet.evidence_ref.source_type,
                        "source_id": packet.evidence_ref.source_id,
                        "source_version": packet.evidence_ref.source_version,
                        "locator": dict(packet.evidence_ref.locator),
                        "status": packet.status.value,
                        "score": packet.relevance_score,
                    }
                )
            context.memory["evidence_packets"] = [
                packet.model_dump(mode="json") for packet in packets
            ]
            citation_builder = getattr(self.evidence_service, "build_citations", None)
            if callable(citation_builder):
                context.memory["evidence_citations"] = [
                    citation.model_dump(mode="json")
                    for citation in citation_builder(packets)
                ]
            context.memory["knowledge_query"] = str(query or "")
            context.memory["knowledge_citation_count"] = len(context.citations)
            return context

        has_restricted_hint = bool(
            scope is not None and scope.mode is ScopeMode.RESTRICTED
        ) or any(
            runtime.get(key)
            for key in (
                "workspace_id",
                "knowledge_document_ids",
                "research_source_ids",
                "research_note_ids",
                "knowledge_item_ids",
            )
        )
        if has_restricted_hint:
            # Legacy Knowledge Runtime has no authoritative document/note scope.
            # Disable it rather than leaking a whole graph into a scoped request.
            context.memory["knowledge_retrieval_status"] = "scoped_runtime_unavailable"
            context.memory["knowledge_query"] = str(query or "")
            context.memory["knowledge_citation_count"] = len(context.citations)
            return context

        if self.knowledge_runtime is None:
            return context

        result = self.knowledge_runtime.build_context(query, top_k=self.top_k)

        knowledge_text = str(
            self._value(result, "context", self._value(result, "context_text", "")) or ""
        ).strip()
        if knowledge_text:
            context.knowledge_context = knowledge_text

        citations = self._value(result, "citations", []) or []
        existing = {
            self._citation_key(item)
            for item in getattr(context, "citations", [])
            if isinstance(item, dict)
        }
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            key = self._citation_key(citation)
            if key in existing:
                continue
            context.add_citation(dict(citation))
            existing.add(key)

        nodes = self._value(
            result,
            "nodes",
            self._value(result, "retrieved_nodes", None),
        )
        if nodes is not None:
            context.memory["knowledge_nodes"] = list(nodes)

        context.memory["knowledge_query"] = str(query or "")
        context.memory["knowledge_citation_count"] = len(context.citations)
        return context


__all__ = ["KnowledgeInjector"]
