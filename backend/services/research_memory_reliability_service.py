from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import re
from typing import Any

from app.research.memory_reliability import ResearchMemoryReliabilityStore
from backend.models.research_memory_reliability import (
    ResearchMemoryConflictGroup,
    ResearchMemoryHitReliability,
    ResearchMemoryReliabilitySummary,
    ResearchMemoryReliableSearchResult,
    ResearchMemorySourceStatus,
)

# Keep this list deliberately conservative. These predicates are expected to
# behave as single-valued assertions for a subject in the structured-memory
# graph. Taxonomic predicates such as ``is_a`` and multi-label predicates such
# as ``classified_as`` are intentionally excluded because multiple targets can
# be simultaneously valid.
_SINGLE_VALUE_PREDICATES = frozenset(
    {
        "defined_as",
        "equal_to",
        "equals",
        "has_value",
    }
)
_PREDICATE_SEPARATOR_RE = re.compile(r"[\s\-/]+")


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _predicate_key(value: object) -> str:
    return _PREDICATE_SEPARATOR_RE.sub("_", _normalized(value)).strip("_")


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class ResearchMemoryReliabilityService:
    """Deterministic freshness, provenance and conservative conflict signals."""

    def __init__(
        self,
        *,
        memory_store: Any,
        research_note_service: Any,
        revision_store: ResearchMemoryReliabilityStore | Any | None = None,
        workspace_service: Any | None = None,
    ) -> None:
        self._memory_store = memory_store
        self._research_notes = research_note_service
        self._revisions = revision_store or ResearchMemoryReliabilityStore()
        self._workspaces = workspace_service

    def record_source_revision(
        self,
        *,
        workspace_id: str,
        note_id: str,
        source_fingerprint: str,
    ) -> None:
        self._revisions.record_source_revision(
            workspace_id=workspace_id,
            note_id=note_id,
            source_fingerprint=source_fingerprint,
        )

    def delete_source_revision(self, *, workspace_id: str, note_id: str) -> bool:
        return bool(
            self._revisions.delete_source_revision(
                workspace_id=workspace_id,
                note_id=note_id,
            )
        )

    def source_status(self, *, workspace_id: str, note_id: str) -> ResearchMemorySourceStatus:
        note = self._research_notes.get(note_id)
        if note is None:
            return "orphaned"

        if self._workspaces is not None:
            profile = self._workspaces.get(workspace_id)
            if profile is None or note_id not in set(profile.note_ids):
                return "detached"

        revision = self._revisions.get_source_revision(
            workspace_id=workspace_id,
            note_id=note_id,
        )
        if revision is None or not revision.source_fingerprint:
            return "legacy_unknown"
        current = str(getattr(note, "fingerprint", "") or "").strip()
        if not current:
            return "legacy_unknown"
        if current != revision.source_fingerprint:
            return "stale"
        return "fresh"

    def conflict_groups(
        self,
        *,
        workspace_id: str,
        snapshot: Any | None = None,
    ) -> tuple[ResearchMemoryConflictGroup, ...]:
        memory = snapshot or self._memory_store.snapshot(workspace_id=workspace_id, limit=500)
        grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)

        for relation in memory.relations:
            predicate = _predicate_key(relation.predicate)
            if predicate not in _SINGLE_VALUE_PREDICATES:
                continue
            status = self.source_status(
                workspace_id=workspace_id,
                note_id=relation.note_id,
            )
            if status not in {"fresh", "legacy_unknown"}:
                continue
            grouped[(relation.source_entity_id, predicate)].append(relation)

        groups: list[ResearchMemoryConflictGroup] = []
        for (subject_id, predicate), relations in grouped.items():
            target_ids = sorted({item.target_entity_id for item in relations})
            if len(target_ids) < 2:
                continue
            payload = "|".join([workspace_id, subject_id, predicate, *target_ids])
            group_id = sha256(payload.encode("utf-8")).hexdigest()[:20]
            groups.append(
                ResearchMemoryConflictGroup(
                    group_id=group_id,
                    workspace_id=workspace_id,
                    subject_entity_id=subject_id,
                    predicate=predicate,
                    target_entity_ids=target_ids,
                    relation_ids=sorted({item.relation_id for item in relations}),
                    claim_ids=sorted({item.claim_id for item in relations if item.claim_id}),
                    note_ids=sorted({item.note_id for item in relations if item.note_id}),
                )
            )

        groups.sort(key=lambda item: (item.predicate, item.subject_entity_id, item.group_id))
        return tuple(groups)

    @staticmethod
    def _provenance_note_ids(*, result: Any, snapshot: Any) -> list[str]:
        evidence_claims = {item.claim_id for item in snapshot.evidence if item.claim_id}
        if result.kind == "evidence":
            return [result.note_id] if result.note_id else []
        if result.kind == "claim":
            if result.claim_id and result.claim_id in evidence_claims and result.note_id:
                return [result.note_id]
            return []
        if result.kind == "relation":
            if result.claim_id and result.claim_id in evidence_claims and result.note_id:
                return [result.note_id]
            return []
        if result.kind != "entity" or not result.entity_id:
            return []

        note_ids: list[str] = []
        for relation in snapshot.relations:
            if (
                relation.source_entity_id != result.entity_id
                and relation.target_entity_id != result.entity_id
            ):
                continue
            if not relation.claim_id or relation.claim_id not in evidence_claims:
                continue
            if relation.note_id:
                note_ids.append(relation.note_id)
        return _dedupe(note_ids)

    def hit_reliability(
        self,
        *,
        workspace_id: str,
        result: Any,
        snapshot: Any | None = None,
        conflict_groups: tuple[ResearchMemoryConflictGroup, ...] | None = None,
    ) -> ResearchMemoryHitReliability:
        memory = snapshot or self._memory_store.snapshot(workspace_id=workspace_id, limit=500)
        source_note_ids = self._provenance_note_ids(result=result, snapshot=memory)
        statuses = [
            self.source_status(workspace_id=workspace_id, note_id=note_id)
            for note_id in source_note_ids
        ]
        usable = any(status in {"fresh", "legacy_unknown"} for status in statuses)

        if "fresh" in statuses:
            source_status: ResearchMemorySourceStatus = "fresh"
        elif "legacy_unknown" in statuses:
            source_status = "legacy_unknown"
        elif "stale" in statuses:
            source_status = "stale"
        elif "detached" in statuses:
            source_status = "detached"
        elif "orphaned" in statuses:
            source_status = "orphaned"
        else:
            source_status = "legacy_unknown"

        groups = conflict_groups
        if groups is None:
            groups = self.conflict_groups(workspace_id=workspace_id, snapshot=memory)
        matching_group_ids: list[str] = []
        for group in groups:
            if result.item_id in group.relation_ids:
                matching_group_ids.append(group.group_id)
                continue
            if result.claim_id and result.claim_id in group.claim_ids:
                matching_group_ids.append(group.group_id)
                continue
            if result.entity_id and (
                result.entity_id == group.subject_entity_id
                or result.entity_id in group.target_entity_ids
            ):
                matching_group_ids.append(group.group_id)

        reasons: list[str] = []
        if not source_note_ids:
            reasons.append("no_grounded_provenance")
        if any(status == "legacy_unknown" for status in statuses):
            reasons.append("source_revision_unavailable")
        if any(status == "stale" for status in statuses):
            reasons.append("stale_source_revision")
        if any(status == "orphaned" for status in statuses):
            reasons.append("source_note_missing")
        if any(status == "detached" for status in statuses):
            reasons.append("source_note_detached_from_workspace")
        if matching_group_ids:
            reasons.append("conflicting_single_value_relation")

        return ResearchMemoryHitReliability(
            source_status=source_status,
            source_note_ids=source_note_ids,
            groundable=usable,
            conflicted=bool(matching_group_ids),
            reason_codes=_dedupe(reasons),
            conflict_group_ids=_dedupe(matching_group_ids),
        )

    def enrich_results(
        self,
        *,
        workspace_id: str,
        results: tuple[Any, ...],
        snapshot: Any | None = None,
    ) -> tuple[ResearchMemoryReliableSearchResult, ...]:
        memory = snapshot or self._memory_store.snapshot(workspace_id=workspace_id, limit=500)
        conflicts = self.conflict_groups(workspace_id=workspace_id, snapshot=memory)
        return tuple(
            ResearchMemoryReliableSearchResult(
                result=result,
                reliability=self.hit_reliability(
                    workspace_id=workspace_id,
                    result=result,
                    snapshot=memory,
                    conflict_groups=conflicts,
                ),
            )
            for result in results
        )

    @staticmethod
    def summarize(
        results: tuple[ResearchMemoryReliableSearchResult, ...],
    ) -> ResearchMemoryReliabilitySummary:
        total = len(results)
        fresh = sum(item.reliability.source_status == "fresh" for item in results)
        legacy = sum(item.reliability.source_status == "legacy_unknown" for item in results)
        stale = sum(item.reliability.source_status == "stale" for item in results)
        orphaned = sum(item.reliability.source_status == "orphaned" for item in results)
        detached = sum(item.reliability.source_status == "detached" for item in results)
        conflicted = sum(item.reliability.conflicted for item in results)
        groundable = sum(item.reliability.groundable for item in results)
        provenance = sum(bool(item.reliability.source_note_ids) for item in results)
        denominator = float(total or 1)
        return ResearchMemoryReliabilitySummary(
            total_hit_count=total,
            fresh_hit_count=fresh,
            legacy_unknown_hit_count=legacy,
            stale_hit_count=stale,
            orphaned_hit_count=orphaned,
            detached_hit_count=detached,
            conflicted_hit_count=conflicted,
            groundable_hit_count=groundable,
            provenance_resolved_count=provenance,
            groundable_hit_rate=groundable / denominator if total else 0.0,
            provenance_resolution_rate=provenance / denominator if total else 0.0,
            conflict_hit_rate=conflicted / denominator if total else 0.0,
            stale_hit_rate=stale / denominator if total else 0.0,
            orphaned_hit_rate=orphaned / denominator if total else 0.0,
            detached_hit_rate=detached / denominator if total else 0.0,
        )


__all__ = ["ResearchMemoryReliabilityService"]
