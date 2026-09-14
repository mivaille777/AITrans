from __future__ import annotations

from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.services.companion_chat_service import CompanionChatResult
from backend.services.grounded_synthesis_service import (
    GROUNDING_VERIFICATION_FALLBACK_PREFIX,
    PARTIAL_GROUNDING_NOTICE,
    GroundedSynthesisService,
)


class _FakeChatService:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.last_payload: dict[str, object] = {}

    def send(self, **kwargs):
        self.last_payload = dict(kwargs)
        return CompanionChatResult(
            session_id=str(kwargs.get("session_id", "session-1")),
            user_message=str(kwargs.get("user_message", "question")),
            output_text=self.output_text,
            provider="test-provider",
            model="test-model",
            request_id=int(kwargs.get("request_id", 1)),
            knowledge_enabled=True,
        )


def _evidence() -> list[AgentEvidenceItem]:
    return [
        AgentEvidenceItem(
            evidence_id="ev-1",
            source_type="knowledge",
            source_id="doc-1",
            title="Optimization paper",
            location="Page 3 · Methods",
            excerpt=(
                "Bayesian optimization improves sample efficiency under costly "
                "evaluations by using a surrogate model."
            ),
        )
    ]


def _citations() -> list[AgentCitationRef]:
    return [
        AgentCitationRef(
            citation_id="cite-1",
            evidence_ids=["ev-1"],
            label="[1]",
        )
    ]


def _send(output_text: str):
    chat = _FakeChatService(output_text)
    result = GroundedSynthesisService(chat_service=chat).send_verified(
        evidence=_evidence(),
        citations=_citations(),
        session_id="session-1",
        user_message="Develop the insight.",
        request_id=7,
    )
    return chat, result


def test_fully_verified_grounded_answer_is_returned_without_notice():
    original = (
        "Bayesian optimization improves sample efficiency under costly "
        "evaluations by using a surrogate model [1]."
    )
    chat, result = _send(original)

    assert result.verification is not None
    assert result.verification.passed is True
    assert result.fallback_applied is False
    assert result.partial_grounding is False
    assert result.answer.output_text == original
    assert result.answer.provider == "test-provider"
    assert "search_knowledge_base" == chat.last_payload["tool_name"]


def test_partially_verified_answer_is_preserved_with_notice():
    original = (
        "Bayesian optimization improves sample efficiency under costly "
        "evaluations by using a surrogate model [1].\n"
        "This broader design can also support contextual reasoning during later analysis."
    )
    _, result = _send(original)

    assert result.verification is not None
    assert result.verification.passed is False
    assert result.verification.invalid_citation_count == 0
    assert result.verification.citation_coverage == 0.5
    assert result.verification.support_rate == 0.5
    assert result.fallback_applied is False
    assert result.partial_grounding is True
    assert result.answer.output_text.startswith(original)
    assert result.answer.output_text.endswith(PARTIAL_GROUNDING_NOTICE)
    assert result.answer.provider == "test-provider"
    assert result.answer.model == "test-model"


def test_trailing_citation_preserves_multi_sentence_academic_paragraph():
    original = (
        "The optimization process is designed for costly evaluations and therefore "
        "benefits from a sample-efficient search strategy. "
        "Bayesian optimization improves sample efficiency under costly evaluations "
        "by using a surrogate model [1]."
    )
    _, result = _send(original)

    assert result.verification is not None
    assert result.verification.passed is False
    assert result.verification.citation_coverage == 0.5
    assert result.verification.paragraph_count == 1
    assert result.verification.cited_paragraph_count == 1
    assert result.verification.supported_paragraph_count == 1
    assert result.verification.paragraph_citation_coverage == 1.0
    assert result.verification.paragraph_support_rate == 1.0
    assert result.fallback_applied is False
    assert result.partial_grounding is True
    assert result.answer.output_text.startswith(original)
    assert result.answer.output_text.endswith(PARTIAL_GROUNDING_NOTICE)


def test_paragraph_level_one_in_three_citation_coverage_is_preserved():
    original = (
        "The method first narrows the candidate region using prior observations.\n"
        "The local reasoning stage then interprets the current control context.\n"
        "Bayesian optimization improves sample efficiency under costly evaluations "
        "by using a surrogate model [1]."
    )
    _, result = _send(original)

    assert result.verification is not None
    assert result.verification.passed is False
    assert result.verification.invalid_citation_count == 0
    assert result.verification.cited_claim_count == 1
    assert result.verification.claim_count == 3
    assert result.verification.supported_claim_count == 1
    assert result.verification.paragraph_citation_coverage == 0.3333
    assert result.fallback_applied is False
    assert result.partial_grounding is True
    assert result.answer.output_text.startswith(original)


def test_answer_with_too_little_citation_coverage_still_falls_back():
    original = (
        "The method first narrows the candidate region using prior observations.\n"
        "The local reasoning stage then interprets the current control context.\n"
        "A separate mechanism constrains how actions are admitted during execution.\n"
        "Bayesian optimization improves sample efficiency under costly evaluations "
        "by using a surrogate model [1]."
    )
    _, result = _send(original)

    assert result.verification is not None
    assert result.verification.cited_claim_count == 1
    assert result.verification.claim_count == 4
    assert result.verification.citation_coverage == 0.25
    assert result.verification.paragraph_citation_coverage == 0.25
    assert result.partial_grounding is False
    assert result.fallback_applied is True
    assert result.answer.model == "grounding-verification-fallback"


def test_unknown_citation_still_triggers_evidence_only_fallback():
    original = (
        "Bayesian optimization improves sample efficiency under costly "
        "evaluations by using a surrogate model [9]."
    )
    _, result = _send(original)

    assert result.verification is not None
    assert result.verification.passed is False
    assert result.verification.invalid_citation_count == 1
    assert result.partial_grounding is False
    assert result.fallback_applied is True
    assert result.answer.provider == "policy"
    assert result.answer.model == "grounding-verification-fallback"
    assert result.answer.output_text.startswith(GROUNDING_VERIFICATION_FALLBACK_PREFIX)
    assert original not in result.answer.output_text
