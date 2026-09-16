from __future__ import annotations

from backend.agent_core.orchestration.evidence_service import (
    ScopedEvidenceCache,
    ScopedEvidenceService,
)
from backend.models.agent_tasks import ScopeContext
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult


class CountingRag:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def retrieve(self, query: str, *, filters, final_top_k: int):
        del final_top_k
        document_id = filters.document_ids[0]
        self.calls.append(tuple(filters.document_ids))
        chunk = DocumentChunk(
            chunk_id=f"chunk-{document_id}",
            document_id=document_id,
            text=f"{query} from {document_id}",
            chunk_index=0,
            document_hash=f"hash-{document_id}",
        )
        return RetrievalResult(
            query=query,
            candidates=[RetrievalCandidate(chunk=chunk, fusion_score=0.8, rank=1)],
        )


def _scope(document_id: str, revision: str, version: str) -> ScopeContext:
    return ScopeContext.issue(
        scope_revision=revision,
        allowed_document_ids=[document_id],
        source_versions={document_id: version},
    )


def test_cache_deduplicates_same_scope_query_and_source_version() -> None:
    rag = CountingRag()
    service = ScopedEvidenceService(rag_retriever=rag, cache=ScopedEvidenceCache())
    scope = _scope("doc-a", "scope-a-r1", "v1")

    first = service.retrieve_packets(query="accuracy", scope=scope)
    second = service.retrieve_packets(query="accuracy", scope=scope)

    assert rag.calls == [("doc-a",)]
    assert first == second
    assert first is not second


def test_cache_does_not_cross_scope_revision_document_or_source_version() -> None:
    rag = CountingRag()
    service = ScopedEvidenceService(rag_retriever=rag, cache=ScopedEvidenceCache())

    service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "scope-a-r1", "v1"))
    service.retrieve_packets(query="accuracy", scope=_scope("doc-b", "scope-b-r1", "v1"))
    service.retrieve_packets(query="accuracy", scope=_scope("doc-a", "scope-a-r2", "v2"))

    assert rag.calls == [("doc-a",), ("doc-b",), ("doc-a",)]
