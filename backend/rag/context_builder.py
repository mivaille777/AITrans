from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil
from typing import Any

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.citation_service import CitationService

DEFAULT_GROUNDED_CONTEXT_TOKENS = 6_000
DEFAULT_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class GroundedContext:
    text: str
    included_evidence_ids: tuple[str, ...]
    omitted_evidence_ids: tuple[str, ...]
    estimated_tokens: int
    max_context_tokens: int


def _rank(item: AgentEvidenceItem) -> int:
    value: Any = item.metadata.get("rank")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 10**9
    return parsed if parsed > 0 else 10**9


def _evidence_order(evidence: list[AgentEvidenceItem]) -> list[AgentEvidenceItem]:
    indexed = list(enumerate(evidence))
    indexed.sort(
        key=lambda pair: (
            _rank(pair[1]),
            -float(pair[1].score) if pair[1].score is not None else float("inf"),
            pair[0],
        )
    )
    return [item for _index, item in indexed]


class GroundedContextBuilder:
    """Build a bounded, citation-allowlisted evidence context for synthesis."""

    def __init__(
        self,
        *,
        max_context_tokens: int = DEFAULT_GROUNDED_CONTEXT_TOKENS,
        chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
    ) -> None:
        self.max_context_tokens = max(1, int(max_context_tokens))
        self.chars_per_token = max(1, int(chars_per_token))
        self.max_context_chars = self.max_context_tokens * self.chars_per_token

    def build(
        self,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
        *,
        context_overrides: Mapping[str, str] | None = None,
    ) -> GroundedContext:
        CitationService().validate(citations, evidence)
        citation_by_evidence: dict[str, AgentCitationRef] = {}
        for citation in citations:
            for evidence_id in citation.evidence_ids:
                citation_by_evidence.setdefault(evidence_id, citation)

        overrides = context_overrides or {}
        allowed = "\n".join(
            f"- {citation.citation_id} => {citation.label} => "
            f"{', '.join(citation.evidence_ids)}"
            for citation in citations
        )
        preamble = (
            "GROUNDING RULES\n"
            "- Answer from the supplied Evidence.\n"
            "- State clearly when Evidence is insufficient.\n"
            "- Do not invent sources, titles, URLs, pages, sections, or citations.\n"
            "- Add citations to factual claims when supported.\n"
            "- Use only the allowed display labels below.\n"
            "- Supplemental same-section context is interpretation-only and is not independently citable.\n"
            "- Do not make a factual claim supported only by Supplemental Context.\n"
            "- Internal retrieval scores are not user facts.\n"
            f"ALLOWED CITATIONS\n{allowed}\n"
            "EVIDENCE\n"
        )
        text = preamble[: self.max_context_chars]
        included: list[str] = []
        omitted: list[str] = []
        for position, item in enumerate(_evidence_order(evidence), start=1):
            citation = citation_by_evidence.get(item.evidence_id)
            if citation is None:
                omitted.append(item.evidence_id)
                continue
            supplemental = str(overrides.get(item.evidence_id, "") or "").strip()
            segment = (
                f"\n[C{position}] {citation.label}\n"
                f"Title: {item.title or 'Untitled source'}\n"
                f"Location: {item.location or 'Location unavailable'}\n"
                f"Evidence: {item.excerpt.strip()}\n"
            )
            if supplemental:
                segment += (
                    "Supplemental Same-Section Context "
                    "(interpretation only; not independently citable):\n"
                    f"{supplemental}\n"
                )
            if len(text) + len(segment) > self.max_context_chars:
                omitted.append(item.evidence_id)
                continue
            text += segment
            included.append(item.evidence_id)

        estimated_tokens = ceil(len(text) / self.chars_per_token) if text else 0
        return GroundedContext(
            text=text,
            included_evidence_ids=tuple(included),
            omitted_evidence_ids=tuple(omitted),
            estimated_tokens=estimated_tokens,
            max_context_tokens=self.max_context_tokens,
        )


__all__ = [
    "DEFAULT_CHARS_PER_TOKEN",
    "DEFAULT_GROUNDED_CONTEXT_TOKENS",
    "GroundedContext",
    "GroundedContextBuilder",
]
