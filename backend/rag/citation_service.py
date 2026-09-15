from __future__ import annotations

from collections.abc import Sequence

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.exceptions import RagInvariantError


class CitationService:
    """Assign program-owned citation identifiers to verified Agent evidence."""

    @staticmethod
    def _evidence_ids(evidence: Sequence[AgentEvidenceItem]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in evidence:
            evidence_id = item.evidence_id.strip()
            if not evidence_id:
                raise RagInvariantError("evidence_id must not be empty")
            if evidence_id not in seen:
                ordered.append(evidence_id)
                seen.add(evidence_id)
        return ordered

    def build(
        self,
        evidence: Sequence[AgentEvidenceItem],
        *,
        evidence_groups: Sequence[Sequence[str]] | None = None,
    ) -> list[AgentCitationRef]:
        available = self._evidence_ids(evidence)
        if not available:
            return []
        available_set = set(available)
        raw_groups = (
            evidence_groups
            if evidence_groups is not None
            else [[evidence_id] for evidence_id in available]
        )

        groups: list[list[str]] = []
        seen_groups: set[tuple[str, ...]] = set()
        for raw_group in raw_groups:
            group: list[str] = []
            seen_evidence: set[str] = set()
            for raw_evidence_id in raw_group:
                evidence_id = str(raw_evidence_id or "").strip()
                if evidence_id not in available_set:
                    raise RagInvariantError(
                        f"citation references unknown evidence_id: {evidence_id!r}"
                    )
                if evidence_id not in seen_evidence:
                    group.append(evidence_id)
                    seen_evidence.add(evidence_id)
            if not group:
                continue
            signature = tuple(group)
            if signature not in seen_groups:
                groups.append(group)
                seen_groups.add(signature)

        citations = [
            AgentCitationRef(
                citation_id=f"citation-{index}",
                evidence_ids=group,
                label=f"[{index}]",
            )
            for index, group in enumerate(groups, start=1)
        ]
        self.validate(citations, evidence)
        return citations

    def validate(
        self,
        citations: Sequence[AgentCitationRef],
        evidence: Sequence[AgentEvidenceItem],
    ) -> None:
        available = set(self._evidence_ids(evidence))
        seen_citation_ids: set[str] = set()
        for citation in citations:
            if not citation.citation_id or citation.citation_id in seen_citation_ids:
                raise RagInvariantError(
                    f"duplicate or empty citation_id: {citation.citation_id!r}"
                )
            seen_citation_ids.add(citation.citation_id)
            if not citation.evidence_ids:
                raise RagInvariantError(
                    f"citation {citation.citation_id!r} has no evidence"
                )
            unknown = [
                evidence_id
                for evidence_id in citation.evidence_ids
                if evidence_id not in available
            ]
            if unknown:
                raise RagInvariantError(
                    f"citation references unknown evidence_id: {unknown[0]!r}"
                )


def build_evidence_citations(
    evidence: Sequence[AgentEvidenceItem],
    *,
    evidence_groups: Sequence[Sequence[str]] | None = None,
) -> list[AgentCitationRef]:
    return CitationService().build(evidence, evidence_groups=evidence_groups)


__all__ = ["CitationService", "build_evidence_citations"]
