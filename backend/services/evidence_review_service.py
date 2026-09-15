from __future__ import annotations

from typing import Any

from app.research.evidence_review import EvidenceReviewRecord, EvidenceReviewStore
from backend.models.evidence_review import (
    EvidenceReview,
    EvidenceReviewSnapshot,
    LiteratureSynthesisItem,
    LiteratureSynthesisPlan,
    ReviewedEvidenceLedgerItem,
)


def _default_review(*, workspace_id: str, entry_id: str) -> EvidenceReview:
    return EvidenceReview(
        entry_id=entry_id,
        workspace_id=workspace_id,
        status="unreviewed",
        note="",
        reviewed_at="",
        updated_at="",
    )


class EvidenceReviewService:
    """Human adjudication and evidence-first literature synthesis for Stage 20."""

    def __init__(self, *, ledger_service: Any, store: EvidenceReviewStore | Any | None = None) -> None:
        self._ledger = ledger_service
        self._store = store or EvidenceReviewStore()

    @staticmethod
    def _review_model(record: EvidenceReviewRecord) -> EvidenceReview:
        return EvidenceReview(
            entry_id=record.entry_id,
            workspace_id=record.workspace_id,
            status=record.status,
            note=record.note,
            reviewed_at=record.reviewed_at,
            updated_at=record.updated_at,
        )

    def review(
        self,
        *,
        workspace_id: str,
        entry_id: str,
        status: str,
        note: str = "",
    ) -> ReviewedEvidenceLedgerItem:
        ledger = self._ledger.get(workspace_id=workspace_id, entry_id=entry_id)
        if ledger is None:
            raise ValueError("Evidence Ledger entry not found.")
        record = self._store.set_review(
            workspace_id=workspace_id,
            entry_id=entry_id,
            status=status,
            note=note,
        )
        return ReviewedEvidenceLedgerItem(ledger=ledger, review=self._review_model(record))

    def snapshot(
        self,
        *,
        workspace_id: str,
        query: str = "",
        limit: int = 100,
    ) -> EvidenceReviewSnapshot:
        ledger = self._ledger.snapshot(workspace_id=workspace_id, query=query, limit=limit)
        reviews = {
            item.entry_id: item
            for item in self._store.list_for_workspace(workspace_id=workspace_id)
        }
        items: list[ReviewedEvidenceLedgerItem] = []
        counts = {"unreviewed": 0, "accepted": 0, "rejected": 0, "needs_review": 0}
        for ledger_item in ledger.items:
            record = reviews.get(ledger_item.entry.entry_id)
            review = (
                self._review_model(record)
                if record is not None
                else _default_review(
                    workspace_id=workspace_id,
                    entry_id=ledger_item.entry.entry_id,
                )
            )
            counts[review.status] += 1
            items.append(ReviewedEvidenceLedgerItem(ledger=ledger_item, review=review))
        return EvidenceReviewSnapshot(
            workspace_id=workspace_id,
            query=query,
            entry_count=len(items),
            unreviewed_count=counts["unreviewed"],
            accepted_count=counts["accepted"],
            rejected_count=counts["rejected"],
            needs_review_count=counts["needs_review"],
            items=items,
        )

    @staticmethod
    def synthesis_bucket(*, machine_status: str, review_status: str) -> tuple[str, str]:
        if review_status != "accepted":
            return "excluded", f"review_{review_status}"
        if machine_status == "supported":
            return "consensus", "accepted_supported"
        if machine_status == "contested":
            return "disagreement", "accepted_contested"
        return "excluded", f"machine_{machine_status}"

    @classmethod
    def _synthesis_item(cls, item: ReviewedEvidenceLedgerItem) -> LiteratureSynthesisItem:
        machine = item.ledger.validation.status
        review = item.review.status
        bucket, reason = cls.synthesis_bucket(machine_status=machine, review_status=review)
        links = item.ledger.entry.links
        return LiteratureSynthesisItem(
            entry_id=item.ledger.entry.entry_id,
            statement=item.ledger.entry.statement,
            machine_status=machine,
            review_status=review,
            bucket=bucket,
            reason=reason,
            document_ids=sorted({link.document_id for link in links}),
            evidence_ids=sorted({link.evidence_id for link in links}),
        )

    @classmethod
    def build_synthesis_plan(cls, snapshot: EvidenceReviewSnapshot) -> LiteratureSynthesisPlan:
        """Build a deterministic plan from one already-revalidated review snapshot.

        Stage 20.1 reuses this method so the LLM sees exactly the same review and
        machine-status decision that the user sees, instead of re-reading a
        potentially different ledger snapshot between policy and generation.
        """

        consensus: list[LiteratureSynthesisItem] = []
        disagreements: list[LiteratureSynthesisItem] = []
        excluded: list[LiteratureSynthesisItem] = []
        for reviewed in snapshot.items:
            item = cls._synthesis_item(reviewed)
            if item.bucket == "consensus":
                consensus.append(item)
            elif item.bucket == "disagreement":
                disagreements.append(item)
            else:
                excluded.append(item)

        def source_label(item: LiteratureSynthesisItem) -> str:
            return ", ".join(f"doc:{document_id}" for document_id in item.document_ids) or "source unavailable"

        lines = ["# Evidence-reviewed literature synthesis", ""]
        if snapshot.query.strip():
            lines.extend([f"Focus: {snapshot.query.strip()}", ""])
        lines.append("## Consensus")
        if consensus:
            lines.extend(f"- {item.statement} [{source_label(item)}]" for item in consensus)
        else:
            lines.append("- No accepted, currently supported claims are available.")
        lines.extend(["", "## Disagreements and open questions"])
        if disagreements:
            lines.extend(f"- {item.statement} [{source_label(item)}]" for item in disagreements)
        else:
            lines.append("- No accepted contested claims are currently available.")
        if excluded:
            lines.extend([
                "",
                "## Review exclusions",
                f"- {len(excluded)} ledger claim(s) were excluded because they were not accepted or are no longer sufficiently grounded.",
            ])

        return LiteratureSynthesisPlan(
            workspace_id=snapshot.workspace_id,
            query=snapshot.query,
            included_count=len(consensus) + len(disagreements),
            excluded_count=len(excluded),
            consensus=consensus,
            disagreements=disagreements,
            excluded=excluded,
            draft_markdown="\n".join(lines),
        )

    def synthesize(
        self,
        *,
        workspace_id: str,
        query: str = "",
        limit: int = 100,
    ) -> LiteratureSynthesisPlan:
        snapshot = self.snapshot(workspace_id=workspace_id, query=query, limit=limit)
        return self.build_synthesis_plan(snapshot)


__all__ = ["EvidenceReviewService"]
