from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_CITATION_RE = re.compile(r"\[(\d+)\]")
_FENCE_RE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.DOTALL | re.IGNORECASE)
_ANSWER_TYPES = {"boolean", "short", "unanswerable"}


@dataclass(frozen=True, slots=True)
class QasperContractAnswer:
    answer: str
    answer_type: str
    citations: tuple[str, ...]
    supporting_explanation: str
    citation_reconciled: bool = False
    citation_label_normalization_count: int = 0
    normalized_extra_keys: tuple[str, ...] = ()
    boolean_prefix_normalized: bool = False

    @property
    def is_unanswerable(self) -> bool:
        return self.answer_type == "unanswerable"


@dataclass(frozen=True, slots=True)
class QasperAnswerContract:
    contract_id: str
    version: int
    max_answer_chars: int
    instructions: str
    raw_sha256: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        raw_sha256: str | None = None,
    ) -> QasperAnswerContract:
        contract_id = str(value.get("contract_id", "")).strip()
        version = value.get("version")
        max_answer_chars = value.get("max_answer_chars")
        instructions = str(value.get("instructions", "")).strip()
        if not contract_id:
            raise ValueError("answer contract requires a contract_id")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("answer contract version must be a positive integer")
        if (
            not isinstance(max_answer_chars, int)
            or isinstance(max_answer_chars, bool)
            or max_answer_chars < 1
        ):
            raise ValueError("answer contract max_answer_chars must be positive")
        if not instructions:
            raise ValueError("answer contract requires instructions")
        canonical_sha256 = raw_sha256 or hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            contract_id=contract_id,
            version=version,
            max_answer_chars=max_answer_chars,
            instructions=instructions,
            raw_sha256=canonical_sha256,
        )

    def append_prompt(self, question: str) -> str:
        return (
            f"Question:\n{question.strip()}\n\n"
            f"Answer contract: {self.contract_id} version {self.version}.\n"
            "Answer using only the Evidence supplied with this request.\n"
            f"{self.instructions}\n"
            "Return one JSON object only. Do not wrap it in Markdown fences. "
            "The object must have exactly these keys: answer, answer_type, "
            "citations, supporting_explanation."
        )

    def manifest(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "version": self.version,
            "sha256": self.raw_sha256,
            "response_schema": {
                "answer": "string",
                "answer_type": sorted(_ANSWER_TYPES),
                "citations": "array of allowed citation labels such as [1]",
                "supporting_explanation": "string",
            },
            "max_answer_chars": self.max_answer_chars,
        }


def parse_qasper_contract_answer(
    raw_output: str,
    *,
    contract: QasperAnswerContract,
    allowed_citations: Sequence[str],
) -> QasperContractAnswer:
    text = str(raw_output or "").strip()
    fenced = _FENCE_RE.fullmatch(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("model output is not one JSON object") from exc
    if not isinstance(payload, dict):
        raise TypeError("model output must be a JSON object")
    required = {"answer", "answer_type", "citations", "supporting_explanation"}
    extra_keys = set(payload).difference(required)
    if required.difference(payload) or extra_keys.difference({"answer_type_note"}):
        raise ValueError("answer contract keys do not match the required schema")
    if "answer_type_note" in extra_keys and str(
        payload["answer_type_note"] or ""
    ).strip().casefold() != str(payload["answer_type"] or "").strip().casefold():
        raise ValueError("redundant answer_type_note conflicts with answer_type")

    answer = payload["answer"]
    answer_type = str(payload["answer_type"] or "").strip().casefold()
    explanation = payload["supporting_explanation"]
    citation_values = payload["citations"]
    if not isinstance(answer, str) or not answer.strip() or "\n" in answer:
        raise ValueError("answer must be a non-empty single-line string")
    answer = answer.strip()
    if len(answer) > contract.max_answer_chars:
        raise ValueError("direct answer exceeds the configured character limit")
    if answer_type not in _ANSWER_TYPES:
        raise ValueError("answer_type is not supported by this contract")
    if not isinstance(explanation, str) or "\n" in explanation:
        raise ValueError("supporting_explanation must be a single-line string")
    explanation = explanation.strip()
    if not isinstance(citation_values, list) or any(
        not isinstance(item, (str, int)) or isinstance(item, bool)
        for item in citation_values
    ):
        raise ValueError("citations must be an array of citation labels")

    citation_label_normalization_count = 0
    explicit_citations: list[str] = []
    for value in citation_values:
        label = str(value).strip()
        if re.fullmatch(r"\d+", label):
            label = f"[{label}]"
            citation_label_normalization_count += 1
        explicit_citations.append(label)
    explicit_citations = list(dict.fromkeys(explicit_citations))
    allowed = {str(item).strip() for item in allowed_citations if str(item).strip()}
    if any(not _CITATION_RE.fullmatch(item) for item in explicit_citations):
        raise ValueError("citations must use the [n] display-label format")
    if set(explicit_citations).difference(allowed):
        raise ValueError("answer cites a label that is not present in supplied evidence")
    text_citations = {
        f"[{number}]"
        for number in _CITATION_RE.findall(f"{answer}\n{explanation}")
    }
    if text_citations.difference(allowed):
        raise ValueError("answer text includes an unknown citation label")
    citation_reconciled = set(explicit_citations) != text_citations
    normalized_citations = tuple(
        dict.fromkeys(
            [*explicit_citations, *sorted(text_citations, key=lambda item: int(item[1:-1]))]
        )
    )

    answer = _CITATION_RE.sub("", answer).strip()
    normalized_answer = re.sub(r"[.!?。！？]+$", "", answer).strip()
    folded_answer = normalized_answer.casefold()
    boolean_prefix_normalized = False
    if answer_type == "boolean":
        if folded_answer not in {"yes", "no"}:
            boolean_prefix = re.match(r"^(yes|no)[.!]\s+", answer, re.IGNORECASE)
            if boolean_prefix is None:
                raise ValueError("boolean answers must be exactly Yes or No")
            folded_answer = boolean_prefix.group(1).casefold()
            boolean_prefix_normalized = True
        answer = "Yes" if folded_answer == "yes" else "No"
    elif answer_type == "unanswerable":
        if folded_answer in {"yes", "no"}:
            raise ValueError("unanswerable answer_type conflicts with Yes/No answer text")
        answer = "Unanswerable"
    elif folded_answer in {"yes", "no", "unanswerable"}:
        raise ValueError("answer_type must match the direct answer")

    if answer_type != "unanswerable" and not normalized_citations:
        raise ValueError("answerable outputs must cite at least one supplied evidence item")
    if answer_type != "unanswerable" and not explanation:
        raise ValueError("answerable outputs require a separate supporting explanation")

    return QasperContractAnswer(
        answer=answer,
        answer_type=answer_type,
        citations=normalized_citations,
        supporting_explanation=explanation,
        citation_reconciled=citation_reconciled,
        citation_label_normalization_count=citation_label_normalization_count,
        normalized_extra_keys=tuple(sorted(extra_keys)),
        boolean_prefix_normalized=boolean_prefix_normalized,
    )


def render_contract_answer(
    answer: QasperContractAnswer,
    *,
    include_partial_grounding_notice: str = "",
) -> str:
    """Render the short scored answer and evidence note as separate fields."""

    if answer.is_unanswerable:
        rendered = "Unanswerable"
        if answer.supporting_explanation:
            explanation = answer.supporting_explanation
            explanation_labels = " ".join(
                label
                for label in answer.citations
                if label not in {
                    f"[{number}]"
                    for number in _CITATION_RE.findall(explanation)
                }
            )
            if explanation_labels:
                explanation = f"{explanation} {explanation_labels}".strip()
            rendered += f"\n\nEvidence note: {explanation}"
    else:
        labels = " ".join(answer.citations)
        rendered = f"Answer: {answer.answer} {labels}".rstrip()
        explanation = answer.supporting_explanation
        explanation_labels = " ".join(
            label
            for label in answer.citations
            if label not in {
                f"[{number}]"
                for number in _CITATION_RE.findall(explanation)
            }
        )
        if explanation_labels:
            explanation = f"{explanation} {explanation_labels}".strip()
        rendered += f"\n\nEvidence note: {explanation}"
    if include_partial_grounding_notice:
        rendered += f"\n\n{include_partial_grounding_notice.strip()}"
    return rendered


def render_contract_for_verification(
    answer: QasperContractAnswer,
) -> str:
    """Convert a valid structured response into citation-bearing prose."""

    return render_contract_answer(answer)


__all__ = [
    "QasperAnswerContract",
    "QasperContractAnswer",
    "parse_qasper_contract_answer",
    "render_contract_answer",
    "render_contract_for_verification",
]
