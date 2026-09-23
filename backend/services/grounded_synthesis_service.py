from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.context_builder import GroundedContext, GroundedContextBuilder
from backend.services.agent_claim_evidence_verifier import (
    AgentClaimEvidenceVerifier,
    ClaimEvidenceVerification,
)
from backend.services.companion_chat_service import CompanionChatResult

NO_KNOWLEDGE_EVIDENCE_MESSAGE = "知识库未找到足够相关证据。"
GROUNDING_VERIFICATION_FALLBACK_PREFIX = (
    "原始回答未通过引用与证据一致性校验。以下仅保留可直接核验的证据："
)
PARTIAL_GROUNDING_NOTICE = (
    "注：部分解释性陈述未能逐句通过引用一致性校验；已保留综合回答，"
    "并仅将现有引用视为可直接核验的证据。"
)
_PARTIAL_MIN_PARAGRAPH_CITATION_COVERAGE = 1.0 / 3.0
_PARTIAL_MIN_PARAGRAPH_SUPPORT_RATE = 0.60
_PARTIAL_MIN_CITATION_COVERAGE = 1.0 / 3.0
_PARTIAL_MIN_CITED_SUPPORT_RATE = 0.75
_FALLBACK_MAX_EVIDENCE_ITEMS = 4
_FALLBACK_MAX_EXCERPT_CHARS = 420


def evidence_only_grounding_fallback(
    *,
    evidence: list[AgentEvidenceItem],
    citations: list[AgentCitationRef],
) -> str:
    """Return a source-owned fallback safe for both Agent and Companion chat."""

    citation_by_evidence: dict[str, str] = {}
    for citation in citations:
        for evidence_id in citation.evidence_ids:
            citation_by_evidence.setdefault(evidence_id, citation.label)

    lines = [GROUNDING_VERIFICATION_FALLBACK_PREFIX]
    for item in evidence[:_FALLBACK_MAX_EVIDENCE_ITEMS]:
        excerpt = " ".join(item.excerpt.strip().split())
        if not excerpt:
            continue
        if len(excerpt) > _FALLBACK_MAX_EXCERPT_CHARS:
            excerpt = excerpt[: _FALLBACK_MAX_EXCERPT_CHARS - 1].rstrip() + "…"
        label = citation_by_evidence.get(item.evidence_id, "")
        title = str(item.title or "").strip() or "Untitled source"
        location = str(item.location or "").strip()
        source_line = f"- {title}"
        if location:
            source_line += f" · {location}"
        if label:
            source_line += f" {label}"
        lines.append(source_line)
        lines.append(f"  {excerpt}")
    if len(lines) == 1:
        return NO_KNOWLEDGE_EVIDENCE_MESSAGE
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class VerifiedGroundedSynthesisResult:
    answer: CompanionChatResult
    verification: ClaimEvidenceVerification | None = None
    fallback_applied: bool = False
    partial_grounding: bool = False


class GroundedSynthesisService:
    """Grounded synthesis plus deterministic post-generation verification.

    The verifier owns the shared release decision used by both synchronous and
    WebSocket production paths. ``strict_passed`` records sentence-level full
    verification; a release-safe paragraph-grounded answer is preserved with a
    notice. Invalid citations and genuinely weak grounding still fall back to
    source-owned evidence only.
    """

    def __init__(
        self,
        *,
        chat_service: Any,
        context_builder: GroundedContextBuilder | None = None,
        verifier: AgentClaimEvidenceVerifier | Any | None = None,
        allow_general_without_evidence: bool = False,
    ) -> None:
        self._chat_service = chat_service
        self._context_builder = context_builder or GroundedContextBuilder()
        self._verifier = verifier or AgentClaimEvidenceVerifier()
        self._allow_general_without_evidence = allow_general_without_evidence

    @property
    def prompt_id(self) -> str:
        return str(getattr(self._chat_service, "prompt_id", "") or "")

    @staticmethod
    def _policy_answer(
        kwargs: dict[str, Any],
        *,
        output_text: str,
        model: str,
    ) -> CompanionChatResult:
        return CompanionChatResult(
            session_id=str(kwargs.get("session_id", "agent-session") or "agent-session"),
            user_message=str(kwargs.get("user_message", "") or ""),
            output_text=output_text,
            provider="policy",
            model=model,
            request_id=max(0, int(kwargs.get("request_id", 0) or 0)),
        )

    @staticmethod
    def _copy_answer(
        answer: Any,
        *,
        output_text: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> CompanionChatResult:
        raw_request_id = getattr(answer, "request_id", 0)
        try:
            request_id = max(0, int(raw_request_id or 0))
        except (TypeError, ValueError):
            request_id = 0

        raw_evidence = getattr(answer, "evidence", ()) or ()
        raw_citations = getattr(answer, "citations", ()) or ()
        return CompanionChatResult(
            session_id=str(getattr(answer, "session_id", "") or ""),
            user_message=str(getattr(answer, "user_message", "") or ""),
            output_text=output_text,
            provider=(
                str(provider)
                if provider is not None
                else str(getattr(answer, "provider", "") or "")
            ),
            model=(
                str(model)
                if model is not None
                else str(getattr(answer, "model", "") or "")
            ),
            request_id=request_id,
            knowledge_enabled=bool(getattr(answer, "knowledge_enabled", False)),
            knowledge_fallback_reason=str(
                getattr(answer, "knowledge_fallback_reason", "") or ""
            ),
            evidence=tuple(raw_evidence),
            citations=tuple(raw_citations),
        )

    @staticmethod
    def _included_grounding(
        context: GroundedContext,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
    ) -> tuple[list[AgentEvidenceItem], list[AgentCitationRef]]:
        included_ids = set(context.included_evidence_ids)
        included_evidence = [
            item for item in evidence if item.evidence_id in included_ids
        ]
        available_ids = {item.evidence_id for item in included_evidence}
        included_citations = [
            AgentCitationRef(
                citation_id=item.citation_id,
                evidence_ids=[
                    evidence_id
                    for evidence_id in item.evidence_ids
                    if evidence_id in available_ids
                ],
                label=item.label,
            )
            for item in citations
            if any(evidence_id in available_ids for evidence_id in item.evidence_ids)
        ]
        return included_evidence, included_citations

    @staticmethod
    def _evidence_only_fallback(
        *,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
    ) -> str:
        return evidence_only_grounding_fallback(
            evidence=evidence,
            citations=citations,
        )

    @staticmethod
    def _preserve_partial_grounding(
        verification: ClaimEvidenceVerification,
    ) -> bool:
        """Compatibility policy for custom/legacy verifier adapters."""

        if verification.invalid_citation_count != 0:
            return False

        paragraph_count = int(getattr(verification, "paragraph_count", 0) or 0)
        cited_paragraph_count = int(
            getattr(verification, "cited_paragraph_count", 0) or 0
        )
        supported_paragraph_count = int(
            getattr(verification, "supported_paragraph_count", 0) or 0
        )
        paragraph_citation_coverage = float(
            getattr(verification, "paragraph_citation_coverage", 0.0) or 0.0
        )
        paragraph_support_rate = float(
            getattr(verification, "paragraph_support_rate", 0.0) or 0.0
        )
        if paragraph_count > 0:
            return (
                cited_paragraph_count > 0
                and supported_paragraph_count > 0
                and paragraph_citation_coverage
                >= _PARTIAL_MIN_PARAGRAPH_CITATION_COVERAGE
                and paragraph_support_rate >= _PARTIAL_MIN_PARAGRAPH_SUPPORT_RATE
            )

        if (
            verification.claim_count <= 0
            or verification.cited_claim_count <= 0
            or verification.supported_claim_count <= 0
            or verification.citation_coverage < _PARTIAL_MIN_CITATION_COVERAGE
        ):
            return False
        cited_support_rate = (
            verification.supported_claim_count / verification.cited_claim_count
        )
        return cited_support_rate >= _PARTIAL_MIN_CITED_SUPPORT_RATE

    def send_verified(
        self,
        *,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
        context_overrides: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> VerifiedGroundedSynthesisResult:
        if not evidence:
            if self._allow_general_without_evidence:
                return VerifiedGroundedSynthesisResult(
                    answer=self._chat_service.send(**kwargs)
                )
            return VerifiedGroundedSynthesisResult(
                answer=self._policy_answer(
                    kwargs,
                    output_text=NO_KNOWLEDGE_EVIDENCE_MESSAGE,
                    model="no-evidence",
                )
            )

        context = self._context_builder.build(
            evidence,
            citations,
            context_overrides=context_overrides,
        )
        if not context.included_evidence_ids:
            return VerifiedGroundedSynthesisResult(
                answer=self._policy_answer(
                    kwargs,
                    output_text=NO_KNOWLEDGE_EVIDENCE_MESSAGE,
                    model="context-budget",
                )
            )

        included_evidence, included_citations = self._included_grounding(
            context, evidence, citations
        )
        payload = dict(kwargs)
        payload["tool_name"] = "search_knowledge_base"
        payload["tool_context"] = context.text
        answer = self._chat_service.send(**payload)
        verification = self._verifier.verify(
            output_text=answer.output_text,
            evidence=included_evidence,
            citations=included_citations,
        )

        strict_passed = bool(
            getattr(verification, "strict_passed", verification.passed)
        )
        if strict_passed:
            return VerifiedGroundedSynthesisResult(
                answer=answer,
                verification=verification,
            )

        release_safe_partial = bool(verification.passed) or bool(
            getattr(verification, "partial_grounding", False)
        )
        if release_safe_partial or self._preserve_partial_grounding(verification):
            partial_answer = self._copy_answer(
                answer,
                output_text=(
                    f"{answer.output_text.rstrip()}\n\n{PARTIAL_GROUNDING_NOTICE}"
                ),
            )
            return VerifiedGroundedSynthesisResult(
                answer=partial_answer,
                verification=verification,
                partial_grounding=True,
            )

        fallback = self._copy_answer(
            answer,
            output_text=self._evidence_only_fallback(
                evidence=included_evidence,
                citations=included_citations,
            ),
            provider="policy",
            model="grounding-verification-fallback",
        )
        return VerifiedGroundedSynthesisResult(
            answer=fallback,
            verification=verification,
            fallback_applied=True,
        )

    def send(
        self,
        *,
        evidence: list[AgentEvidenceItem],
        citations: list[AgentCitationRef],
        **kwargs: Any,
    ) -> CompanionChatResult:
        return self.send_verified(
            evidence=evidence,
            citations=citations,
            **kwargs,
        ).answer

    def close(self) -> None:
        close = getattr(self._chat_service, "close", None)
        if callable(close):
            close()


__all__ = [
    "GROUNDING_VERIFICATION_FALLBACK_PREFIX",
    "NO_KNOWLEDGE_EVIDENCE_MESSAGE",
    "PARTIAL_GROUNDING_NOTICE",
    "GroundedSynthesisService",
    "VerifiedGroundedSynthesisResult",
    "evidence_only_grounding_fallback",
]
