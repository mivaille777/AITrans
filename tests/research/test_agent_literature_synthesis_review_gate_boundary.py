from __future__ import annotations

from types import SimpleNamespace

from backend.services.agent_literature_synthesis_service import AgentLiteratureSynthesisService


class _Memory:
    def __init__(self, raw_excerpt: str) -> None:
        self.raw_excerpt = raw_excerpt

    def snapshot(self, *, workspace_id: str, limit: int = 500):
        _ = (workspace_id, limit)
        return SimpleNamespace(
            evidence=(
                SimpleNamespace(
                    evidence_id="evidence-1",
                    note_id="note-1",
                    excerpt=self.raw_excerpt,
                ),
            )
        )

    def source_status(self, *, workspace_id: str, note_id: str) -> str:
        _ = (workspace_id, note_id)
        return "fresh"


class _Notes:
    @staticmethod
    def get(note_id: str):
        _ = note_id
        return SimpleNamespace(
            display_title="Reviewed paper",
            section_heading="Method",
            resource_url="file:///reviewed-paper.pdf",
        )


def test_agent_context_exposes_reviewed_ledger_statement_not_raw_rag_excerpt() -> None:
    reviewed_statement = "The reviewed claim states that the GP constrains the broad search region."
    raw_rag_only_fact = "RAW_RAG_ONLY_FACT: the same snippet also reports an unreviewed 37 percent gain."

    link = SimpleNamespace(
        evidence_id="evidence-1",
        note_id="note-1",
        document_id="doc-1",
        role="supporting",
        confidence=0.91,
    )
    snapshot = SimpleNamespace(
        items=[
            SimpleNamespace(
                ledger=SimpleNamespace(
                    entry=SimpleNamespace(entry_id="entry-1", links=[link])
                )
            )
        ]
    )
    synthesis_item = SimpleNamespace(
        entry_id="entry-1",
        evidence_ids=["evidence-1"],
        bucket="consensus",
        statement=reviewed_statement,
        machine_status="supported",
        review_status="accepted",
    )
    plan = SimpleNamespace(
        workspace_id="ws",
        consensus=[synthesis_item],
        disagreements=[],
    )

    service = AgentLiteratureSynthesisService(
        review_service=None,
        research_memory_service=_Memory(raw_rag_only_fact),
        research_note_service=_Notes(),
        grounded_synthesis_service=None,
    )

    evidence = service._build_evidence(snapshot=snapshot, plan=plan)

    assert len(evidence) == 1
    assert reviewed_statement in evidence[0].excerpt
    assert raw_rag_only_fact not in evidence[0].excerpt
    assert evidence[0].source_type == "evidence_ledger"
    assert evidence[0].metadata["raw_source_excerpt_exposed"] is False
