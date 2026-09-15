from __future__ import annotations

import re
from typing import Any

from app.research.evidence_ledger import (
    EvidenceLedgerEntryRecord,
    EvidenceLedgerLinkDraft,
    EvidenceLedgerLinkRecord,
    EvidenceLedgerStore,
)
from backend.models.cross_document_research import (
    CrossDocumentAnalysis,
    CrossDocumentSupport,
)
from backend.models.evidence_ledger import (
    EvidenceLedgerEntry,
    EvidenceLedgerItem,
    EvidenceLedgerLink,
    EvidenceLedgerSnapshot,
    EvidenceLedgerValidation,
)

_USABLE_SOURCE_STATUSES = frozenset({"fresh", "legacy_unknown"})
_QUERY_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _tokens(value: object) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in _QUERY_TOKEN_RE.findall(_normalized(value)):
        token = raw.strip("_-")
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return tuple(result)


def _matches(query_tokens: tuple[str, ...], value: object) -> bool:
    if not query_tokens:
        return True
    text = _normalized(value)
    return any(token in text for token in query_tokens)


class EvidenceLedgerService:
    """Persist and revalidate Claim-centered cross-document research conclusions.

    The ledger stores stable provenance identifiers, never copied source text.
    Every read revalidates those identifiers against the live Stage 17 memory
    snapshot and source-reliability state before assigning a current status.
    """

    def __init__(
        self,
        *,
        store: EvidenceLedgerStore | Any | None = None,
        research_memory_service: Any,
        cross_document_service: Any | None = None,
    ) -> None:
        self._store = store or EvidenceLedgerStore()
        self._memory = research_memory_service
        self._cross_document = cross_document_service

    @staticmethod
    def _drafts(
        supports: list[CrossDocumentSupport] | tuple[CrossDocumentSupport, ...],
        *,
        role: str,
    ) -> list[EvidenceLedgerLinkDraft]:
        links: list[EvidenceLedgerLinkDraft] = []
        for support in supports:
            for evidence_id in support.evidence_ids:
                links.append(
                    EvidenceLedgerLinkDraft(
                        role=role,
                        support_kind=support.kind,
                        claim_id=support.claim_id,
                        relation_id=support.relation_id,
                        evidence_id=evidence_id,
                        note_id=support.note_id,
                        document_id=support.document_id,
                        confidence=support.confidence,
                        captured_source_status=support.source_status,
                    )
                )
        return links

    def capture_analysis(self, analysis: CrossDocumentAnalysis) -> tuple[str, ...]:
        workspace_id = analysis.workspace_id.strip()
        if not workspace_id:
            raise ValueError("Evidence Ledger capture requires an active Research Workspace.")
        # Validate the Workspace through the existing Stage 17 boundary.
        self._memory.snapshot(workspace_id=workspace_id, limit=1)

        entry_ids: list[str] = []
        for agreement in analysis.agreements:
            record = self._store.upsert_entry(
                workspace_id=workspace_id,
                entry_kind=agreement.kind,
                statement=agreement.statement,
                origin_kind="stage18_agreement",
                origin_id=agreement.cluster_id,
                query=analysis.query,
                links=self._drafts(agreement.supports, role="supporting"),
            )
            entry_ids.append(record.entry_id)

        for disagreement in analysis.disagreements:
            for alternative in disagreement.alternatives:
                supporting = self._drafts(alternative.supports, role="supporting")
                conflicting_supports: list[CrossDocumentSupport] = []
                for other in disagreement.alternatives:
                    if other.target_entity_id == alternative.target_entity_id:
                        continue
                    conflicting_supports.extend(other.supports)
                conflicting = self._drafts(conflicting_supports, role="conflicting")
                statement = (
                    f"{disagreement.subject_name} {disagreement.predicate} "
                    f"{alternative.target_name}"
                )
                record = self._store.upsert_entry(
                    workspace_id=workspace_id,
                    entry_kind="relation",
                    statement=statement,
                    origin_kind="stage18_disagreement",
                    origin_id=disagreement.group_id,
                    query=analysis.query,
                    links=[*supporting, *conflicting],
                )
                entry_ids.append(record.entry_id)

        return tuple(dict.fromkeys(entry_ids))

    def capture_query(self, *, workspace_id: str, query: str) -> tuple[str, ...]:
        if self._cross_document is None:
            raise RuntimeError("Cross-document research analysis is unavailable.")
        analysis = self._cross_document.analyze(
            workspace_id=workspace_id,
            query=query,
        )
        return self.capture_analysis(analysis)

    @staticmethod
    def _link_model(record: EvidenceLedgerLinkRecord) -> EvidenceLedgerLink:
        return EvidenceLedgerLink(
            link_id=record.link_id,
            role=record.role,
            support_kind=record.support_kind,
            claim_id=record.claim_id,
            relation_id=record.relation_id,
            evidence_id=record.evidence_id,
            note_id=record.note_id,
            document_id=record.document_id,
            confidence=record.confidence,
            captured_source_status=record.captured_source_status,
        )

    def _entry_model(self, record: EvidenceLedgerEntryRecord) -> EvidenceLedgerEntry:
        links = self._store.links_for_entry(record.entry_id)
        return EvidenceLedgerEntry(
            entry_id=record.entry_id,
            workspace_id=record.workspace_id,
            entry_kind=record.entry_kind,
            statement=record.statement,
            normalized_statement=record.normalized_statement,
            origin_kind=record.origin_kind,
            origin_id=record.origin_id,
            query=record.query,
            created_at=record.created_at,
            updated_at=record.updated_at,
            links=[self._link_model(item) for item in links],
        )

    def _validate(
        self,
        entry: EvidenceLedgerEntry,
        *,
        snapshot: Any,
    ) -> EvidenceLedgerValidation:
        evidence_by_id = {item.evidence_id: item for item in snapshot.evidence}
        claim_by_id = {item.claim_id: item for item in snapshot.claims}
        relation_by_id = {item.relation_id: item for item in snapshot.relations}

        usable_supports = 0
        usable_conflicts = 0
        support_documents: set[str] = set()
        conflict_documents: set[str] = set()
        usable_documents: set[str] = set()
        stale_links = 0
        missing_links = 0

        for link in entry.links:
            evidence = evidence_by_id.get(link.evidence_id)
            claim = claim_by_id.get(link.claim_id) if link.claim_id else None
            relation = relation_by_id.get(link.relation_id) if link.relation_id else None
            provenance_matches = (
                evidence is not None
                and (not link.claim_id or claim is not None)
                and (not link.relation_id or relation is not None)
                and evidence.note_id == link.note_id
                and (not link.claim_id or evidence.claim_id == link.claim_id)
            )
            if not provenance_matches:
                missing_links += 1
                continue

            status = str(
                self._memory.source_status(
                    workspace_id=entry.workspace_id,
                    note_id=link.note_id,
                )
                or "legacy_unknown"
            )
            if status not in _USABLE_SOURCE_STATUSES:
                stale_links += 1
                continue

            usable_documents.add(link.document_id)
            if link.role == "supporting":
                usable_supports += 1
                support_documents.add(link.document_id)
            else:
                usable_conflicts += 1
                conflict_documents.add(link.document_id)

        reasons: list[str] = []
        if missing_links:
            reasons.append("provenance_missing")
        if stale_links:
            reasons.append("source_unusable")

        if (
            usable_supports > 0
            and usable_conflicts > 0
            and len(usable_documents) >= 2
        ):
            status = "contested"
            reasons.append("conflicting_evidence")
        elif len(support_documents) >= 2:
            status = "supported"
            reasons.append("cross_document_support")
        elif usable_supports == 0 and usable_conflicts == 0 and entry.links:
            status = "stale"
            reasons.append("all_provenance_unusable")
        else:
            status = "insufficient"
            reasons.append("insufficient_distinct_sources")

        record = self._store.record_validation(
            entry_id=entry.entry_id,
            status=status,
            usable_support_count=usable_supports,
            usable_conflict_count=usable_conflicts,
            supporting_document_count=len(support_documents),
            conflicting_document_count=len(conflict_documents),
            stale_link_count=stale_links,
            missing_link_count=missing_links,
            reason_codes=reasons,
        )
        return EvidenceLedgerValidation(
            status=record.status,
            usable_support_count=record.usable_support_count,
            usable_conflict_count=record.usable_conflict_count,
            supporting_document_count=record.supporting_document_count,
            conflicting_document_count=record.conflicting_document_count,
            stale_link_count=record.stale_link_count,
            missing_link_count=record.missing_link_count,
            reason_codes=list(record.reason_codes),
            checked_at=record.checked_at,
        )

    def snapshot(
        self,
        *,
        workspace_id: str,
        query: str = "",
        limit: int = 100,
    ) -> EvidenceLedgerSnapshot:
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ValueError("Evidence Ledger requires an active Research Workspace.")
        memory_snapshot = self._memory.snapshot(workspace_id=workspace, limit=500)
        query_tokens = _tokens(query)
        items: list[EvidenceLedgerItem] = []
        for record in self._store.list_entries(workspace_id=workspace, limit=limit):
            if not _matches(query_tokens, record.statement):
                continue
            entry = self._entry_model(record)
            validation = self._validate(entry, snapshot=memory_snapshot)
            items.append(EvidenceLedgerItem(entry=entry, validation=validation))

        items.sort(
            key=lambda item: (
                {"contested": 3, "supported": 2, "insufficient": 1, "stale": 0}[
                    item.validation.status
                ],
                item.entry.updated_at,
                item.entry.entry_id,
            ),
            reverse=True,
        )
        counts = {"supported": 0, "contested": 0, "insufficient": 0, "stale": 0}
        for item in items:
            counts[item.validation.status] += 1
        return EvidenceLedgerSnapshot(
            workspace_id=workspace,
            query=str(query or "").strip(),
            entry_count=len(items),
            supported_count=counts["supported"],
            contested_count=counts["contested"],
            insufficient_count=counts["insufficient"],
            stale_count=counts["stale"],
            items=items,
        )

    def get(self, *, workspace_id: str, entry_id: str) -> EvidenceLedgerItem | None:
        record = self._store.get_entry(entry_id)
        if record is None or record.workspace_id != str(workspace_id or "").strip():
            return None
        memory_snapshot = self._memory.snapshot(workspace_id=record.workspace_id, limit=500)
        entry = self._entry_model(record)
        return EvidenceLedgerItem(
            entry=entry,
            validation=self._validate(entry, snapshot=memory_snapshot),
        )


__all__ = ["EvidenceLedgerService"]
