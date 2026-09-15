from __future__ import annotations

from types import SimpleNamespace

from app.ai.errors import AIResponseError
from app.research.notes import ResearchNote
from backend.models.evidence_ledger import (
    EvidenceLedgerEntry,
    EvidenceLedgerItem,
    EvidenceLedgerLink,
    EvidenceLedgerValidation,
)
from backend.models.evidence_review import (
    EvidenceReview,
    EvidenceReviewSnapshot,
    ReviewedEvidenceLedgerItem,
)
from backend.services.agent_literature_synthesis_service import (
    AGENT_LITERATURE_SYNTHESIS_PROMPT_ID,
    AgentLiteratureSynthesisService,
)
from backend.services.companion_chat_service import CompanionChatResult
from backend.services.evidence_review_service import EvidenceReviewService
from backend.services.grounded_synthesis_service import GroundedSynthesisService


def _reviewed(
    *,
    entry_id: str,
    evidence_id: str,
    statement: str,
    machine_status: str = "supported",
    review_status: str = "accepted",
    role: str = "supporting",
    document_id: str = "doc-1",
    note_id: str = "note-1",
) -> ReviewedEvidenceLedgerItem:
    link = EvidenceLedgerLink(
        link_id=f"link-{entry_id}-{evidence_id}",
        role=role,
        support_kind="claim",
        claim_id=f"claim-{entry_id}",
        relation_id="",
        evidence_id=evidence_id,
        note_id=note_id,
        document_id=document_id,
        confidence=0.91,
        captured_source_status="fresh",
    )
    entry = EvidenceLedgerEntry(
        entry_id=entry_id,
        workspace_id="ws",
        entry_kind="claim",
        statement=statement,
        normalized_statement=statement.casefold(),
        origin_kind="stage18_agreement",
        origin_id=f"origin-{entry_id}",
        query="",
        created_at="2026-09-02T00:00:00+00:00",
        updated_at="2026-09-02T00:00:00+00:00",
        links=[link],
    )
    validation = EvidenceLedgerValidation(
        status=machine_status,
        usable_support_count=1 if role == "supporting" else 0,
        usable_conflict_count=1 if role == "conflicting" else 0,
        supporting_document_count=1 if role == "supporting" else 0,
        conflicting_document_count=1 if role == "conflicting" else 0,
        stale_link_count=0,
        missing_link_count=0,
        reason_codes=["test"],
        checked_at="2026-09-02T00:00:00+00:00",
    )
    return ReviewedEvidenceLedgerItem(
        ledger=EvidenceLedgerItem(entry=entry, validation=validation),
        review=EvidenceReview(
            entry_id=entry_id,
            workspace_id="ws",
            status=review_status,
            note="",
            reviewed_at="2026-09-02T00:00:00+00:00" if review_status != "unreviewed" else "",
            updated_at="2026-09-02T00:00:00+00:00" if review_status != "unreviewed" else "",
        ),
    )


class FakeReviews:
    def __init__(self, items: list[ReviewedEvidenceLedgerItem]) -> None:
        self.items = items

    def snapshot(self, *, workspace_id: str, query: str = "", limit: int = 100):
        _ = limit
        counts = {"unreviewed": 0, "accepted": 0, "rejected": 0, "needs_review": 0}
        for item in self.items:
            counts[item.review.status] += 1
        return EvidenceReviewSnapshot(
            workspace_id=workspace_id,
            query=query,
            entry_count=len(self.items),
            unreviewed_count=counts["unreviewed"],
            accepted_count=counts["accepted"],
            rejected_count=counts["rejected"],
            needs_review_count=counts["needs_review"],
            items=self.items,
        )

    @staticmethod
    def build_synthesis_plan(snapshot: EvidenceReviewSnapshot):
        return EvidenceReviewService.build_synthesis_plan(snapshot)


class FakeMemory:
    def __init__(self, excerpts: dict[str, tuple[str, str]], statuses: dict[str, str] | None = None) -> None:
        self.excerpts = excerpts
        self.statuses = statuses or {}

    def snapshot(self, *, workspace_id: str, limit: int = 500):
        _ = (workspace_id, limit)
        evidence = tuple(
            SimpleNamespace(evidence_id=evidence_id, note_id=note_id, excerpt=excerpt)
            for evidence_id, (note_id, excerpt) in self.excerpts.items()
        )
        return SimpleNamespace(evidence=evidence)

    def source_status(self, *, workspace_id: str, note_id: str):
        _ = workspace_id
        return self.statuses.get(note_id, "fresh")


class FakeNotes:
    def __init__(self) -> None:
        self.notes = {
            "note-1": ResearchNote(
                note_id="note-1",
                fingerprint="f1",
                created_at="2026-09-02T00:00:00+00:00",
                updated_at="2026-09-02T00:00:00+00:00",
                resource_url="file:///paper-a.pdf",
                resource_title="Paper A",
                section_heading="Method",
                source_kind="pdf",
                source_text="source",
            ),
            "note-2": ResearchNote(
                note_id="note-2",
                fingerprint="f2",
                created_at="2026-09-02T00:00:00+00:00",
                updated_at="2026-09-02T00:00:00+00:00",
                resource_url="file:///paper-b.pdf",
                resource_title="Paper B",
                section_heading="Results",
                source_kind="pdf",
                source_text="source",
            ),
        }

    def get(self, note_id: str):
        return self.notes.get(note_id)


class CapturingChat:
    prompt_id = "chat.reading@test"

    def __init__(self, output_text: str, *, error: Exception | None = None) -> None:
        self.output_text = output_text
        self.error = error
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return CompanionChatResult(
            session_id=kwargs["session_id"],
            user_message=kwargs["user_message"],
            output_text=self.output_text,
            provider="fake-literature-agent",
            model="literature-model",
            request_id=kwargs.get("request_id", 0),
        )


def _service(items, memory, chat) -> AgentLiteratureSynthesisService:
    return AgentLiteratureSynthesisService(
        review_service=FakeReviews(items),
        research_memory_service=memory,
        research_note_service=FakeNotes(),
        grounded_synthesis_service=GroundedSynthesisService(chat_service=chat),
    )


def test_agent_synthesis_uses_only_review_gate_admitted_evidence() -> None:
    accepted = _reviewed(
        entry_id="accepted",
        evidence_id="evidence-a",
        statement="The GP constrains the broad search region.",
    )
    rejected = _reviewed(
        entry_id="rejected",
        evidence_id="evidence-b",
        statement="Rejected material must never enter synthesis.",
        review_status="rejected",
        document_id="doc-2",
        note_id="note-2",
    )
    memory = FakeMemory(
        {
            "evidence-a": ("note-1", "The GP constrains the broad search region for PID tuning."),
            "evidence-b": ("note-2", "Rejected material must never enter synthesis."),
        }
    )
    chat = CapturingChat("The GP constrains the broad search region for PID tuning [1].")

    result = _service([accepted, rejected], memory, chat).generate(
        workspace_id="ws",
        query="How is the search region constrained?",
    )

    assert result.status == "completed"
    assert result.fallback_applied is False
    assert result.prompt_id == AGENT_LITERATURE_SYNTHESIS_PROMPT_ID
    assert result.included_count == 1
    assert result.excluded_count == 1
    assert result.evidence_count == 1
    assert result.verification is not None and result.verification.passed is True
    assert len(chat.calls) == 1
    call = chat.calls[0]
    assert call["context_mode"] == "general"
    assert call["source_text"] == ""
    assert "Rejected material" not in call["tool_context"]
    assert "Review-gated ledger claim (consensus; provenance role=supporting)" in call["tool_context"]
    assert "Source evidence: The GP constrains the broad search region" in call["tool_context"]


def test_agent_synthesis_preserves_contested_claim_as_disagreement_context() -> None:
    contested = _reviewed(
        entry_id="contested",
        evidence_id="evidence-c",
        statement="The studies disagree on whether adaptation reduces settling time.",
        machine_status="contested",
        role="conflicting",
    )
    memory = FakeMemory(
        {"evidence-c": ("note-1", "The reported settling-time effect differs across the evaluated conditions.")}
    )
    chat = CapturingChat(
        "The studies disagree on whether adaptation reduces settling time across the evaluated conditions [1]."
    )

    result = _service([contested], memory, chat).generate(workspace_id="ws")

    assert result.status == "completed"
    assert result.plan.consensus == []
    assert len(result.plan.disagreements) == 1
    assert "disagreement · conflicting" in chat.calls[0]["tool_context"]


def test_agent_synthesis_grounding_failure_returns_deterministic_plan() -> None:
    accepted = _reviewed(
        entry_id="accepted",
        evidence_id="evidence-a",
        statement="The GP constrains the broad search region.",
    )
    memory = FakeMemory(
        {"evidence-a": ("note-1", "The GP constrains the broad search region for PID tuning.")}
    )
    chat = CapturingChat("The model invents an unsupported numerical improvement without any citation.")

    result = _service([accepted], memory, chat).generate(workspace_id="ws")

    assert result.status == "fallback"
    assert result.fallback_applied is True
    assert result.fallback_reason == "grounding_verification_failed"
    assert result.provider == "policy"
    assert result.output_text == result.plan.draft_markdown
    assert result.verification is not None and result.verification.passed is False


def test_agent_synthesis_provider_failure_returns_deterministic_plan() -> None:
    accepted = _reviewed(
        entry_id="accepted",
        evidence_id="evidence-a",
        statement="The GP constrains the broad search region.",
    )
    memory = FakeMemory(
        {"evidence-a": ("note-1", "The GP constrains the broad search region for PID tuning.")}
    )
    chat = CapturingChat("", error=AIResponseError("provider failed"))

    result = _service([accepted], memory, chat).generate(workspace_id="ws")

    assert result.status == "fallback"
    assert result.fallback_reason == "model_unavailable"
    assert result.output_text == result.plan.draft_markdown


def test_agent_synthesis_skips_model_when_review_gate_has_no_evidence() -> None:
    stale = _reviewed(
        entry_id="stale",
        evidence_id="evidence-a",
        statement="This claim is stale and must not enter model context.",
        machine_status="stale",
    )
    chat = CapturingChat("should not run")

    result = _service(
        [stale],
        FakeMemory({"evidence-a": ("note-1", "stale source")}),
        chat,
    ).generate(workspace_id="ws")

    assert result.status == "no_evidence"
    assert result.fallback_applied is False
    assert result.fallback_reason == "no_reviewed_evidence"
    assert result.evidence_count == 0
    assert chat.calls == []


def test_agent_synthesis_rechecks_source_status_before_model_context() -> None:
    accepted = _reviewed(
        entry_id="accepted",
        evidence_id="evidence-a",
        statement="The GP constrains the broad search region.",
    )
    memory = FakeMemory(
        {"evidence-a": ("note-1", "The GP constrains the broad search region for PID tuning.")},
        statuses={"note-1": "stale"},
    )
    chat = CapturingChat("should not run")

    result = _service([accepted], memory, chat).generate(workspace_id="ws")

    assert result.status == "fallback"
    assert result.fallback_reason == "reviewed_provenance_unavailable"
    assert chat.calls == []
