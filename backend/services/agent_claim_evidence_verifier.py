from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem

_CITATION_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？；;])\s+|\n+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n+")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")

_STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "are",
    "was",
    "were",
    "into",
    "than",
    "then",
    "have",
    "has",
    "had",
    "can",
    "could",
    "would",
    "should",
    "about",
    "based",
    "using",
    "use",
    "根据",
    "可以",
    "以及",
    "一个",
    "这种",
    "这些",
    "其中",
}


@dataclass(frozen=True, slots=True)
class ClaimEvidenceVerification:
    passed: bool
    claim_count: int
    cited_claim_count: int
    supported_claim_count: int
    unsupported_claim_count: int
    invalid_citation_count: int
    citation_coverage: float
    support_rate: float
    reason_codes: tuple[str, ...] = ()
    paragraph_count: int = 0
    cited_paragraph_count: int = 0
    supported_paragraph_count: int = 0
    paragraph_citation_coverage: float = 0.0
    paragraph_support_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class ClaimEvidenceVerifierPolicy:
    minimum_claim_chars: int = 16
    minimum_support_score: float = 0.22
    minimum_citation_coverage: float = 1.0
    minimum_support_rate: float = 1.0
    minimum_paragraph_support_score: float = 0.16

    def __post_init__(self) -> None:
        if self.minimum_claim_chars < 1:
            raise ValueError("minimum_claim_chars must be positive")
        for name, value in (
            ("minimum_support_score", self.minimum_support_score),
            ("minimum_citation_coverage", self.minimum_citation_coverage),
            ("minimum_support_rate", self.minimum_support_rate),
            ("minimum_paragraph_support_score", self.minimum_paragraph_support_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")


class AgentClaimEvidenceVerifier:
    """Deterministically verify citation coverage and lexical evidence support.

    Strict pass/fail remains sentence based. Paragraph-level signals are also
    collected for the synthesis layer because academic prose commonly places a
    citation at the end of a paragraph rather than after every sentence. Those
    paragraph signals never make an invalid/unknown citation valid; they only
    let the caller distinguish useful partially grounded synthesis from a true
    grounding failure.
    """

    def __init__(self, policy: ClaimEvidenceVerifierPolicy | None = None) -> None:
        self.policy = policy or ClaimEvidenceVerifierPolicy()

    @staticmethod
    def _strip_citations(text: str) -> str:
        return _CITATION_RE.sub("", text).strip(" \t-*•#:")

    @staticmethod
    def _tokens(text: str) -> set[str]:
        tokens: set[str] = set()
        cjk: list[str] = []
        for raw in _WORD_RE.findall(str(text or "")):
            if len(raw) == 1 and "\u4e00" <= raw <= "\u9fff":
                cjk.append(raw)
                continue
            token = raw.lower()
            if len(token) >= 2 and token not in _STOPWORDS:
                tokens.add(token)
        compact_cjk = "".join(cjk)
        if len(compact_cjk) >= 2:
            tokens.update(
                compact_cjk[index : index + 2]
                for index in range(len(compact_cjk) - 1)
            )
        return tokens

    def _is_verifiable_unit(self, text: str) -> bool:
        body = self._strip_citations(text)
        compact = re.sub(r"\s+", "", body)
        return (
            len(compact) >= self.policy.minimum_claim_chars
            and bool(self._tokens(body))
        )

    def _claims(self, output_text: str) -> tuple[str, ...]:
        return tuple(
            candidate
            for raw in _SENTENCE_SPLIT_RE.split(str(output_text or ""))
            if (candidate := raw.strip()) and self._is_verifiable_unit(candidate)
        )

    def _paragraphs(self, output_text: str) -> tuple[str, ...]:
        paragraphs: list[str] = []
        for raw in _PARAGRAPH_SPLIT_RE.split(str(output_text or "")):
            candidate = raw.strip()
            if not candidate or not self._is_verifiable_unit(candidate):
                continue
            # Markdown headings are organizational labels, not evidence claims.
            if candidate.lstrip().startswith("#"):
                continue
            paragraphs.append(candidate)
        return tuple(paragraphs)

    @staticmethod
    def _citation_map(
        citations: Sequence[AgentCitationRef],
    ) -> dict[str, tuple[str, ...]]:
        return {
            citation.label.strip(): tuple(citation.evidence_ids)
            for citation in citations
            if citation.label.strip()
        }

    @staticmethod
    def _evidence_map(
        evidence: Sequence[AgentEvidenceItem],
    ) -> dict[str, AgentEvidenceItem]:
        return {
            item.evidence_id: item
            for item in evidence
            if item.evidence_id
        }

    def _support_score(self, claim: str, item: AgentEvidenceItem) -> float:
        claim_tokens = self._tokens(self._strip_citations(claim))
        evidence_tokens = self._tokens(
            " ".join((item.title, item.location, item.excerpt))
        )
        if not claim_tokens or not evidence_tokens:
            return 0.0
        overlap = len(claim_tokens & evidence_tokens)
        return overlap / max(1, len(claim_tokens))

    def _paragraph_support_score(self, paragraph: str, item: AgentEvidenceItem) -> float:
        paragraph_tokens = self._tokens(self._strip_citations(paragraph))
        evidence_tokens = self._tokens(
            " ".join((item.title, item.location, item.excerpt))
        )
        if not paragraph_tokens or not evidence_tokens:
            return 0.0
        overlap = len(paragraph_tokens & evidence_tokens)
        # Long synthesis paragraphs should not be penalized merely for adding
        # explanation around a shorter evidence excerpt. Normalizing by the
        # smaller vocabulary retains a conservative lexical-overlap check while
        # making paragraph-end citations usable in real academic prose.
        return overlap / max(1, min(len(paragraph_tokens), len(evidence_tokens)))

    @staticmethod
    def _labels(text: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(f"[{match}]" for match in _CITATION_RE.findall(text))
        )

    def _referenced_evidence(
        self,
        *,
        labels: Sequence[str],
        citation_map: dict[str, tuple[str, ...]],
        evidence_map: dict[str, AgentEvidenceItem],
    ) -> tuple[list[AgentEvidenceItem], int, set[str]]:
        referenced: list[AgentEvidenceItem] = []
        invalid_citations = 0
        reasons: set[str] = set()
        for label in labels:
            evidence_ids = citation_map.get(label)
            if not evidence_ids:
                invalid_citations += 1
                reasons.add("unknown_citation")
                continue
            for evidence_id in evidence_ids:
                item = evidence_map.get(evidence_id)
                if item is None:
                    invalid_citations += 1
                    reasons.add("citation_missing_evidence")
                else:
                    referenced.append(item)
        return referenced, invalid_citations, reasons

    def verify(
        self,
        *,
        output_text: str,
        evidence: Sequence[AgentEvidenceItem],
        citations: Sequence[AgentCitationRef],
    ) -> ClaimEvidenceVerification:
        claims = self._claims(output_text)
        paragraphs = self._paragraphs(output_text)
        citation_map = self._citation_map(citations)
        evidence_map = self._evidence_map(evidence)

        cited_paragraphs = 0
        supported_paragraphs = 0
        paragraph_invalid_citations = 0
        paragraph_reasons: set[str] = set()
        for paragraph in paragraphs:
            labels = self._labels(paragraph)
            if not labels:
                continue
            cited_paragraphs += 1
            referenced, invalid, reasons = self._referenced_evidence(
                labels=labels,
                citation_map=citation_map,
                evidence_map=evidence_map,
            )
            paragraph_invalid_citations += invalid
            paragraph_reasons.update(reasons)
            if invalid or not referenced:
                continue
            if max(
                self._paragraph_support_score(paragraph, item)
                for item in referenced
            ) >= self.policy.minimum_paragraph_support_score:
                supported_paragraphs += 1

        paragraph_count = len(paragraphs)
        paragraph_citation_coverage = (
            cited_paragraphs / paragraph_count if paragraph_count else 1.0
        )
        paragraph_support_rate = (
            supported_paragraphs / cited_paragraphs if cited_paragraphs else 0.0
        )

        if not claims:
            return ClaimEvidenceVerification(
                passed=True,
                claim_count=0,
                cited_claim_count=0,
                supported_claim_count=0,
                unsupported_claim_count=0,
                invalid_citation_count=paragraph_invalid_citations,
                citation_coverage=1.0,
                support_rate=1.0,
                reason_codes=("no_verifiable_claims",),
                paragraph_count=paragraph_count,
                cited_paragraph_count=cited_paragraphs,
                supported_paragraph_count=supported_paragraphs,
                paragraph_citation_coverage=round(paragraph_citation_coverage, 4),
                paragraph_support_rate=round(paragraph_support_rate, 4),
            )

        cited_claims = 0
        supported_claims = 0
        invalid_citations = 0
        reasons: set[str] = set(paragraph_reasons)

        for claim in claims:
            labels = self._labels(claim)
            if not labels:
                reasons.add("missing_claim_citation")
                continue
            cited_claims += 1

            referenced, invalid, reference_reasons = self._referenced_evidence(
                labels=labels,
                citation_map=citation_map,
                evidence_map=evidence_map,
            )
            invalid_citations += invalid
            reasons.update(reference_reasons)
            if invalid or not referenced:
                continue
            if max(self._support_score(claim, item) for item in referenced) >= self.policy.minimum_support_score:
                supported_claims += 1
            else:
                reasons.add("weak_claim_evidence_overlap")

        # Paragraph parsing can encounter the same invalid label that sentence
        # parsing already counted. The safety question is whether any invalid
        # citation exists, so keep the stricter non-zero signal without double
        # counting identical textual references.
        invalid_citations = max(invalid_citations, paragraph_invalid_citations)

        claim_count = len(claims)
        citation_coverage = cited_claims / claim_count
        support_rate = supported_claims / claim_count
        if citation_coverage < self.policy.minimum_citation_coverage:
            reasons.add("citation_coverage_below_policy")
        if support_rate < self.policy.minimum_support_rate:
            reasons.add("claim_support_below_policy")

        passed = (
            invalid_citations == 0
            and citation_coverage >= self.policy.minimum_citation_coverage
            and support_rate >= self.policy.minimum_support_rate
        )
        return ClaimEvidenceVerification(
            passed=passed,
            claim_count=claim_count,
            cited_claim_count=cited_claims,
            supported_claim_count=supported_claims,
            unsupported_claim_count=max(0, claim_count - supported_claims),
            invalid_citation_count=invalid_citations,
            citation_coverage=round(citation_coverage, 4),
            support_rate=round(support_rate, 4),
            reason_codes=tuple(sorted(reasons)),
            paragraph_count=paragraph_count,
            cited_paragraph_count=cited_paragraphs,
            supported_paragraph_count=supported_paragraphs,
            paragraph_citation_coverage=round(paragraph_citation_coverage, 4),
            paragraph_support_rate=round(paragraph_support_rate, 4),
        )


__all__ = [
    "AgentClaimEvidenceVerifier",
    "ClaimEvidenceVerification",
    "ClaimEvidenceVerifierPolicy",
]
