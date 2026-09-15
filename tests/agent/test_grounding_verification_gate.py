from __future__ import annotations

from types import SimpleNamespace

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.citation_service import build_evidence_citations
from backend.services.grounded_synthesis_service import (
    GROUNDING_VERIFICATION_FALLBACK_PREFIX,
    GroundedSynthesisService,
)


class StaticChat:
    prompt_id = "agent-synthesis@verification-test"

    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            session_id=kwargs.get("session_id", "session"),
            user_message=kwargs.get("user_message", "question"),
            output_text=self.output_text,
            provider="fake-synthesis",
            model="fake-model",
            request_id=kwargs.get("request_id", 0),
        )


def _evidence() -> list[AgentEvidenceItem]:
    return [
        AgentEvidenceItem(
            evidence_id="evidence:gp",
            source_type="knowledge",
            source_id="doc-control",
            title="Control Paper",
            location="Section 3.4",
            excerpt="The GP constrains the broad search region.",
            score=0.91,
            metadata={"rank": 1},
        )
    ]


def _kwargs() -> dict:
    return {
        "session_id": "verification",
        "user_message": "How does the GP help?",
        "source_text": "Reading context",
        "request_id": 7,
    }


def test_supported_grounded_answer_is_released_unchanged() -> None:
    evidence = _evidence()
    chat = StaticChat("The GP constrains the broad search region [1].")
    service = GroundedSynthesisService(chat_service=chat)

    result = service.send_verified(
        evidence=evidence,
        citations=build_evidence_citations(evidence),
        **_kwargs(),
    )

    assert result.verification is not None
    assert result.verification.passed is True
    assert result.fallback_applied is False
    assert result.answer.output_text == "The GP constrains the broad search region [1]."
    assert result.answer.provider == "fake-synthesis"


def test_unsupported_claim_is_replaced_by_evidence_only_fallback() -> None:
    evidence = _evidence()
    chat = StaticChat(
        "The GP guarantees global optimality and removes all safety constraints [1]."
    )
    service = GroundedSynthesisService(chat_service=chat)

    result = service.send_verified(
        evidence=evidence,
        citations=build_evidence_citations(evidence),
        **_kwargs(),
    )

    assert result.verification is not None
    assert result.verification.passed is False
    assert result.fallback_applied is True
    assert result.answer.provider == "policy"
    assert result.answer.model == "grounding-verification-fallback"
    assert result.answer.output_text.startswith(GROUNDING_VERIFICATION_FALLBACK_PREFIX)
    assert "The GP constrains the broad search region." in result.answer.output_text
    assert "[1]" in result.answer.output_text
    assert "guarantees global optimality" not in result.answer.output_text


def test_missing_claim_citation_triggers_fallback() -> None:
    evidence = _evidence()
    service = GroundedSynthesisService(
        chat_service=StaticChat("The GP constrains the broad search region during optimization.")
    )

    result = service.send_verified(
        evidence=evidence,
        citations=build_evidence_citations(evidence),
        **_kwargs(),
    )

    assert result.verification is not None
    assert "missing_claim_citation" in result.verification.reason_codes
    assert result.fallback_applied is True


def test_backward_compatible_send_returns_verified_answer_object() -> None:
    evidence = _evidence()
    service = GroundedSynthesisService(
        chat_service=StaticChat("The GP constrains the broad search region [1].")
    )

    answer = service.send(
        evidence=evidence,
        citations=build_evidence_citations(evidence),
        **_kwargs(),
    )

    assert answer.output_text == "The GP constrains the broad search region [1]."
