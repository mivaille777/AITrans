from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import re
from typing import Any

from backend.models.cross_document_research import (
    CrossDocumentAgreement,
    CrossDocumentAlternative,
    CrossDocumentAnalysis,
    CrossDocumentDisagreement,
    CrossDocumentSource,
    CrossDocumentSupport,
)

_QUERY_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_USABLE_SOURCE_STATUSES = frozenset({"fresh", "legacy_unknown"})


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


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(_normalized(part) for part in parts)
    return f"{prefix}-{sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _matches_query(query_tokens: tuple[str, ...], *values: object) -> bool:
    if not query_tokens:
        return True
    haystack = _normalized(" ".join(str(value or "") for value in values))
    return any(token in haystack for token in query_tokens)


class CrossDocumentResearchService:
    """Deterministic multi-document synthesis over reliable structured memory.

    Stage 18 deliberately separates *aggregation* from prose generation. This
    service only identifies source documents, repeated exact propositions and
    conservative cross-document disagreements. Every support must retain live
    Claim/Evidence provenance back to a Research Note.
    """

    def __init__(
        self,
        *,
        research_memory_service: Any,
        research_note_service: Any,
    ) -> None:
        self._memory = research_memory_service
        self._notes = research_note_service

    @staticmethod
    def _document_identity(note: Any) -> tuple[str, str, str]:
        resource_url = str(getattr(note, "resource_url", "") or "").strip()
        title = str(getattr(note, "resource_title", "") or "").strip()
        note_id = str(getattr(note, "note_id", "") or "").strip()
        if resource_url:
            identity_kind = "url"
            identity_value = resource_url
        elif title:
            identity_kind = "title"
            identity_value = title
        else:
            identity_kind = "note"
            identity_value = note_id
        document_id = _stable_id("doc", identity_kind, identity_value)
        return document_id, title, resource_url

    def _sources(self, snapshot: Any) -> tuple[dict[str, CrossDocumentSource], dict[str, str]]:
        mutable: dict[str, dict[str, Any]] = {}
        document_by_note: dict[str, str] = {}
        note_ids = {
            str(item.note_id or "")
            for item in (*snapshot.claims, *snapshot.evidence, *snapshot.relations)
            if str(item.note_id or "")
        }
        for note_id in sorted(note_ids):
            note = self._notes.get(note_id)
            if note is None:
                continue
            document_id, title, resource_url = self._document_identity(note)
            document_by_note[note_id] = document_id
            item = mutable.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "title": title,
                    "resource_url": resource_url,
                    "note_ids": [],
                },
            )
            item["note_ids"].append(note_id)
            if not item["title"] and title:
                item["title"] = title
            if not item["resource_url"] and resource_url:
                item["resource_url"] = resource_url

        sources = {
            key: CrossDocumentSource(
                document_id=value["document_id"],
                title=value["title"],
                resource_url=value["resource_url"],
                note_ids=sorted(set(value["note_ids"])),
            )
            for key, value in mutable.items()
        }
        return sources, document_by_note

    @staticmethod
    def _evidence_by_claim(snapshot: Any) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = defaultdict(list)
        for evidence in snapshot.evidence:
            if evidence.claim_id:
                mapping[evidence.claim_id].append(evidence.evidence_id)
        return {
            claim_id: list(dict.fromkeys(evidence_ids))
            for claim_id, evidence_ids in mapping.items()
        }

    def _support(
        self,
        *,
        kind: str,
        claim_id: str,
        relation_id: str,
        note_id: str,
        document_by_note: dict[str, str],
        text: str,
        evidence_ids: list[str],
        confidence: float,
        workspace_id: str,
    ) -> CrossDocumentSupport | None:
        document_id = document_by_note.get(note_id, "")
        if not document_id or not evidence_ids:
            return None
        status = str(
            self._memory.source_status(
                workspace_id=workspace_id,
                note_id=note_id,
            )
            or "legacy_unknown"
        )
        if status not in _USABLE_SOURCE_STATUSES:
            return None
        return CrossDocumentSupport(
            support_id=_stable_id("support", kind, claim_id, relation_id, note_id),
            kind=kind,
            claim_id=claim_id,
            relation_id=relation_id,
            note_id=note_id,
            document_id=document_id,
            text=text,
            evidence_ids=evidence_ids,
            source_status=status,
            confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        )

    def analyze(
        self,
        *,
        workspace_id: str,
        query: str = "",
        agreement_limit: int = 24,
        disagreement_limit: int = 16,
    ) -> CrossDocumentAnalysis:
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ValueError("Cross-document research requires an active Research Workspace.")
        snapshot = self._memory.snapshot(workspace_id=workspace, limit=500)
        sources, document_by_note = self._sources(snapshot)
        evidence_by_claim = self._evidence_by_claim(snapshot)
        entity_by_id = {item.entity_id: item for item in snapshot.entities}
        query_tokens = _tokens(query)

        claim_groups: dict[str, list[CrossDocumentSupport]] = defaultdict(list)
        for claim in snapshot.claims:
            evidence_ids = evidence_by_claim.get(claim.claim_id, [])
            support = self._support(
                kind="claim",
                claim_id=claim.claim_id,
                relation_id="",
                note_id=claim.note_id,
                document_by_note=document_by_note,
                text=claim.text,
                evidence_ids=evidence_ids,
                confidence=claim.confidence,
                workspace_id=workspace,
            )
            if support is not None:
                claim_groups[claim.normalized_text].append(support)

        relation_groups: dict[str, list[CrossDocumentSupport]] = defaultdict(list)
        relation_statement_by_key: dict[str, str] = {}
        for relation in snapshot.relations:
            if not relation.claim_id:
                continue
            source = entity_by_id.get(relation.source_entity_id)
            target = entity_by_id.get(relation.target_entity_id)
            if source is None or target is None:
                continue
            statement = f"{source.canonical_name} {relation.predicate} {target.canonical_name}"
            relation_key = "\x1f".join(
                (
                    source.normalized_name,
                    _normalized(relation.predicate),
                    target.normalized_name,
                )
            )
            support = self._support(
                kind="relation",
                claim_id=relation.claim_id,
                relation_id=relation.relation_id,
                note_id=relation.note_id,
                document_by_note=document_by_note,
                text=statement,
                evidence_ids=evidence_by_claim.get(relation.claim_id, []),
                confidence=relation.confidence,
                workspace_id=workspace,
            )
            if support is not None:
                relation_groups[relation_key].append(support)
                relation_statement_by_key[relation_key] = statement

        agreements: list[CrossDocumentAgreement] = []
        for normalized_text, supports in claim_groups.items():
            document_ids = sorted({item.document_id for item in supports})
            if len(document_ids) < 2:
                continue
            statement = supports[0].text
            if not _matches_query(query_tokens, statement):
                continue
            agreements.append(
                CrossDocumentAgreement(
                    cluster_id=_stable_id("agreement", "claim", normalized_text),
                    kind="claim",
                    key=normalized_text,
                    statement=statement,
                    document_ids=document_ids,
                    supports=sorted(supports, key=lambda item: (item.document_id, item.support_id)),
                )
            )

        for relation_key, supports in relation_groups.items():
            document_ids = sorted({item.document_id for item in supports})
            if len(document_ids) < 2:
                continue
            statement = relation_statement_by_key[relation_key]
            if not _matches_query(query_tokens, statement):
                continue
            agreements.append(
                CrossDocumentAgreement(
                    cluster_id=_stable_id("agreement", "relation", relation_key),
                    kind="relation",
                    key=relation_key,
                    statement=statement,
                    document_ids=document_ids,
                    supports=sorted(supports, key=lambda item: (item.document_id, item.support_id)),
                )
            )

        agreements.sort(
            key=lambda item: (len(item.document_ids), len(item.supports), item.statement.casefold()),
            reverse=True,
        )
        agreements = agreements[: max(1, min(128, int(agreement_limit)))]

        relation_by_id = {item.relation_id: item for item in snapshot.relations}
        disagreements: list[CrossDocumentDisagreement] = []
        for conflict in self._memory.conflict_groups(workspace_id=workspace):
            subject = entity_by_id.get(conflict.subject_entity_id)
            if subject is None:
                continue
            alternatives_by_target: dict[str, list[CrossDocumentSupport]] = defaultdict(list)
            for relation_id in conflict.relation_ids:
                relation = relation_by_id.get(relation_id)
                if relation is None:
                    continue
                target = entity_by_id.get(relation.target_entity_id)
                if target is None or not relation.claim_id:
                    continue
                statement = f"{subject.canonical_name} {relation.predicate} {target.canonical_name}"
                support = self._support(
                    kind="relation",
                    claim_id=relation.claim_id,
                    relation_id=relation.relation_id,
                    note_id=relation.note_id,
                    document_by_note=document_by_note,
                    text=statement,
                    evidence_ids=evidence_by_claim.get(relation.claim_id, []),
                    confidence=relation.confidence,
                    workspace_id=workspace,
                )
                if support is not None:
                    alternatives_by_target[relation.target_entity_id].append(support)

            alternatives: list[CrossDocumentAlternative] = []
            all_documents: set[str] = set()
            for target_entity_id, supports in alternatives_by_target.items():
                target = entity_by_id.get(target_entity_id)
                if target is None or not supports:
                    continue
                document_ids = sorted({item.document_id for item in supports})
                all_documents.update(document_ids)
                alternatives.append(
                    CrossDocumentAlternative(
                        target_entity_id=target_entity_id,
                        target_name=target.canonical_name,
                        document_ids=document_ids,
                        supports=sorted(supports, key=lambda item: (item.document_id, item.support_id)),
                    )
                )
            if len(alternatives) < 2 or len(all_documents) < 2:
                continue
            if not _matches_query(
                query_tokens,
                subject.canonical_name,
                conflict.predicate,
                *(item.target_name for item in alternatives),
            ):
                continue
            alternatives.sort(key=lambda item: (len(item.document_ids), item.target_name.casefold()), reverse=True)
            disagreements.append(
                CrossDocumentDisagreement(
                    group_id=conflict.group_id,
                    subject_entity_id=conflict.subject_entity_id,
                    subject_name=subject.canonical_name,
                    predicate=conflict.predicate,
                    document_ids=sorted(all_documents),
                    alternatives=alternatives,
                )
            )

        disagreements.sort(
            key=lambda item: (len(item.document_ids), item.subject_name.casefold(), item.predicate),
            reverse=True,
        )
        disagreements = disagreements[: max(1, min(64, int(disagreement_limit)))]

        usable_claim_supports = sum(len(items) for items in claim_groups.values())
        usable_relation_supports = sum(len(items) for items in relation_groups.values())
        source_list = sorted(
            sources.values(),
            key=lambda item: ((item.title or item.resource_url).casefold(), item.document_id),
        )
        return CrossDocumentAnalysis(
            workspace_id=workspace,
            query=str(query or "").strip(),
            document_count=len(source_list),
            source_count=len(source_list),
            claim_support_count=usable_claim_supports,
            relation_support_count=usable_relation_supports,
            agreement_count=len(agreements),
            disagreement_count=len(disagreements),
            sources=source_list,
            agreements=agreements,
            disagreements=disagreements,
        )


__all__ = ["CrossDocumentResearchService"]
