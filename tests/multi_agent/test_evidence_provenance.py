from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.orchestration.evidence_service import ScopedEvidenceService
from backend.models.agent_tasks import ScopeContext
from backend.rag.models import DocumentChunk, RetrievalCandidate, RetrievalResult


class Rag:
    def retrieve(self, query: str, *, filters, final_top_k: int):
        assert filters.document_ids == ["doc-a"]
        chunk = DocumentChunk(
            chunk_id="chunk-table-1",
            document_id="doc-a",
            text="Table 2 reports accuracy 91.2%.",
            title="Paper A",
            section_heading="Experiments",
            section_path=["Results", "Ablation"],
            chunk_type="table",
            page_number=7,
            chunk_index=3,
            start_char=120,
            end_char=154,
            source_uri="file:///paper-a.pdf",
            document_hash="hash-doc-a",
            metadata={"table_id": "table-2", "image_id": "figure-3"},
        )
        return RetrievalResult(
            query=query,
            candidates=[RetrievalCandidate(chunk=chunk, rerank_score=0.93, rank=1)],
            retrieval_strategy="hybrid",
        )


def test_document_evidence_preserves_page_table_image_and_version_locator() -> None:
    scope = ScopeContext.issue(
        scope_revision="doc-a-r2",
        allowed_document_ids=["doc-a"],
        source_versions={"doc-a": "version-2"},
    )

    packet = ScopedEvidenceService(rag_retriever=Rag()).retrieve_packets(
        query="accuracy",
        scope=scope,
    )[0]

    assert packet.evidence_ref.source_id == "doc-a"
    assert packet.evidence_ref.source_version == "version-2"
    assert packet.locator.page_number == 7
    assert packet.locator.table_id == "table-2"
    assert packet.locator.image_id == "figure-3"
    assert packet.evidence_ref.locator["chunk_id"] == "chunk-table-1"

    evidence = ScopedEvidenceService.to_agent_evidence([packet])
    citations = ScopedEvidenceService.build_citations([packet])
    assert evidence[0].evidence_id == "chunk:chunk-table-1"
    assert citations[0].evidence_ids == ["chunk:chunk-table-1"]
    assert citations[0].label == "[1]"


class ReviewService:
    def __init__(self) -> None:
        self.review_calls = 0

    def snapshot(self, *, workspace_id: str, query: str, limit: int):
        del query, limit
        assert workspace_id == "workspace-a"
        accepted = SimpleNamespace(
            review=SimpleNamespace(status="accepted"),
            ledger=SimpleNamespace(
                validation=SimpleNamespace(status="supported"),
                entry=SimpleNamespace(
                    entry_id="entry-accepted",
                    statement="alpha is supported",
                    updated_at="2026-09-16T00:00:00Z",
                    links=[SimpleNamespace(document_id="doc-a", note_id="note-a", evidence_id="ev-a")],
                ),
            ),
        )
        rejected = SimpleNamespace(
            review=SimpleNamespace(status="rejected"),
            ledger=SimpleNamespace(
                validation=SimpleNamespace(status="supported"),
                entry=SimpleNamespace(
                    entry_id="entry-rejected",
                    statement="must stay excluded",
                    updated_at="2026-09-16T00:00:00Z",
                    links=[SimpleNamespace(document_id="doc-a", note_id="note-a", evidence_id="ev-r")],
                ),
            ),
        )
        return SimpleNamespace(items=[accepted, rejected])


def test_review_gate_exposes_only_human_accepted_supported_evidence_without_mutation() -> None:
    reviews = ReviewService()
    scope = ScopeContext.issue(
        scope_revision="workspace-a-review",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a"],
        allowed_note_ids=["note-a"],
    )

    packets = ScopedEvidenceService(evidence_review=reviews).retrieve_packets(
        query="alpha",
        scope=scope,
    )

    assert [packet.evidence_ref.evidence_id for packet in packets] == ["ledger:entry-accepted"]
    assert packets[0].review_status == "accepted"
    assert reviews.review_calls == 0


def test_restricted_review_scope_requires_both_exact_document_and_note_membership() -> None:
    scope = ScopeContext.issue(
        scope_revision="workspace-a-document-only",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a"],
    )

    packets = ScopedEvidenceService(evidence_review=ReviewService()).retrieve_packets(
        query="alpha",
        scope=scope,
    )

    assert packets == ()
