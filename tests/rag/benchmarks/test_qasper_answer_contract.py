from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.chat.models import ChatResult
from backend.rag.benchmarks.qasper.answer_contract import (
    QasperAnswerContract,
    parse_qasper_contract_answer,
    render_contract_answer,
)
from backend.rag.benchmarks.qasper.runner import (
    GroundedQasperAnswerer,
    QasperAnswerInput,
    _GroundedChatAdapter,
)
from backend.rag.models import RetrievalResult

PROFILE = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "rag"
    / "benchmarks"
    / "qasper"
    / "profiles"
    / "p1q2-direct-answer-v1.json"
)
POLARITY_PROFILE = PROFILE.with_name("p1q2-direct-answer-v2.json")


def _contract() -> QasperAnswerContract:
    return QasperAnswerContract.from_mapping(json.loads(PROFILE.read_text("utf-8")))


def _response(
    answer: str = "Yes",
    *,
    answer_type: str = "boolean",
    citations: list[str] | None = None,
    explanation: str = "The experiment reports the downstream evaluation result.",
) -> str:
    return json.dumps(
        {
            "answer": answer,
            "answer_type": answer_type,
            "citations": citations if citations is not None else ["[1]"],
            "supporting_explanation": explanation,
        }
    )


def test_contract_parses_short_boolean_answer_and_renders_separate_evidence() -> None:
    result = parse_qasper_contract_answer(
        _response(),
        contract=_contract(),
        allowed_citations=("[1]", "[2]"),
    )

    assert result.answer == "Yes"
    assert result.answer_type == "boolean"
    assert result.citations == ("[1]",)
    rendered = render_contract_answer(result)
    assert rendered.startswith("Answer: Yes [1]")
    assert "Evidence note: The experiment reports" in rendered


@pytest.mark.parametrize(
    ("answer", "answer_type"),
    [("Probably yes", "boolean"), ("Unanswerable", "boolean"), ("No", "short")],
)
def test_contract_rejects_ambiguous_or_mismatched_boolean_labels(
    answer: str,
    answer_type: str,
) -> None:
    with pytest.raises(ValueError):
        parse_qasper_contract_answer(
            _response(answer, answer_type=answer_type),
            contract=_contract(),
            allowed_citations=("[1]",),
        )


def test_contract_rejects_unknown_and_reconciles_allowed_citations() -> None:
    with pytest.raises(ValueError, match="not present"):
        parse_qasper_contract_answer(
            _response(citations=["[2]"]),
            contract=_contract(),
            allowed_citations=("[1]",),
        )
    reconciled = parse_qasper_contract_answer(
        _response(answer="Yes [1]", citations=[]),
        contract=_contract(),
        allowed_citations=("[1]",),
    )
    assert reconciled.citations == ("[1]",)
    assert reconciled.citation_reconciled is True


def test_contract_normalizes_numeric_citation_ids_from_json() -> None:
    parsed = parse_qasper_contract_answer(
        _response(citations=[1]),
        contract=_contract(),
        allowed_citations=("[1]",),
    )

    assert parsed.citations == ("[1]",)
    assert parsed.citation_label_normalization_count == 1


def test_contract_only_normalizes_redundant_matching_answer_type_note() -> None:
    payload = json.loads(_response())
    payload["answer_type_note"] = "BOOLEAN"
    parsed = parse_qasper_contract_answer(
        json.dumps(payload),
        contract=_contract(),
        allowed_citations=("[1]",),
    )
    assert parsed.normalized_extra_keys == ("answer_type_note",)

    payload["unexpected"] = "ignore me"
    with pytest.raises(ValueError, match="required schema"):
        parse_qasper_contract_answer(
            json.dumps(payload),
            contract=_contract(),
            allowed_citations=("[1]",),
        )


def test_contract_separates_leading_boolean_from_following_explanation() -> None:
    parsed = parse_qasper_contract_answer(
        _response(
            "No. The experts have legal training.",
            answer_type="boolean",
        ),
        contract=_contract(),
        allowed_citations=("[1]",),
    )

    assert parsed.answer == "No"
    assert parsed.boolean_prefix_normalized is True


def test_contract_parses_unanswerable_without_claiming_negative_answer() -> None:
    result = parse_qasper_contract_answer(
        _response(
            "Unanswerable",
            answer_type="unanswerable",
            citations=[],
            explanation="",
        ),
        contract=_contract(),
        allowed_citations=("[1]",),
    )

    assert result.answer == "Unanswerable"
    assert result.is_unanswerable
    assert render_contract_answer(result) == "Unanswerable"


def test_contract_normalizes_natural_abstention_label_and_accepts_supported_long_answer() -> None:
    abstention = parse_qasper_contract_answer(
        _response(
            "The evidence does not specify the requested item.",
            answer_type="unanswerable",
            citations=[],
            explanation="",
        ),
        contract=_contract(),
        allowed_citations=("[1]",),
    )
    long_answer = "A precise source-grounded definition. " + ("Detailed answer. " * 17)
    answer = parse_qasper_contract_answer(
        _response(long_answer, answer_type="short"),
        contract=_contract(),
        allowed_citations=("[1]",),
    )

    assert abstention.answer == "Unanswerable"
    assert answer.answer == long_answer.strip()


def test_malformed_structured_response_is_rejected() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_qasper_contract_answer(
            "Yes, the paper reports it.",
            contract=_contract(),
            allowed_citations=("[1]",),
        )


class _FakeChatService:
    def __init__(self, output: str) -> None:
        self.output = output
        self.request = None

    def execute(self, request):
        self.request = request
        return ChatResult(
            session_id=request.session_id,
            user_message=request.user_message,
            output_text=self.output,
            provider="fake",
            model="contract-test",
        )


def test_chat_adapter_preserves_raw_output_and_verifies_rendered_contract() -> None:
    raw_output = _response()
    chat_service = _FakeChatService(raw_output)
    adapter = _GroundedChatAdapter(chat_service, answer_contract=_contract())

    normalized = adapter.send(
        user_message="Does the paper report a downstream evaluation?",
        answer_contract_citation_labels=["[1]"],
        tool_context="ALLOWED CITATIONS\n- citation-1 => [1] => evidence:a",
    )

    assert adapter.last_raw_model_output == raw_output
    assert adapter.last_contract_answer is not None
    assert normalized.output_text.startswith("Answer: Yes [1]")
    assert "supporting_explanation" not in normalized.output_text
    assert "p1q2-direct-answer-v1" in chat_service.request.user_message
    assert not hasattr(QasperAnswerInput("q1", "p1", "question"), "answers")


def test_experimental_boolean_polarity_profile_loads_and_requires_entailment() -> None:
    contract = QasperAnswerContract.from_mapping(
        json.loads(POLARITY_PROFILE.read_text("utf-8"))
    )
    prompt = contract.append_prompt("Do they evaluate the model?")

    assert contract.version == 2
    assert "answer Yes only when the Evidence states or entails P" in prompt
    assert "answer No only when the Evidence states or entails not-P" in prompt


class _UnusedTextService:
    provider_name = "fake"
    model = "must-not-be-called"


def test_empty_evidence_abstains_without_calling_provider_under_contract() -> None:
    answerer = GroundedQasperAnswerer(
        text_service=_UnusedTextService(),
        answer_contract=json.loads(PROFILE.read_text("utf-8")),
    )

    answer = answerer(
        QasperAnswerInput("q1", "paper1", "Is the result positive?"),
        RetrievalResult(query="Is the result positive?"),
    )

    assert answer.answer == "Unanswerable"
    assert answer.user_visible_answer == "Unanswerable"
    assert answer.metadata["abstained"] is True
    assert answer.metadata["reason"] == "no_retrieved_evidence"
