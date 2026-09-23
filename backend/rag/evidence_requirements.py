from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from backend.rag.models import RetrievalCandidate
from backend.rag.sparse.tokenizer import SparseTokenizer

RequirementStatus = Literal["covered", "missing"]

_TYPE_QUERIES = {
    "method": "method approach methodology procedure algorithm technique",
    "result": "result finding outcome effect performance accuracy improvement",
    "data": "dataset data sample participant corpus population",
    "rationale": "reason rationale explanation cause",
    "limitation": "limitation weakness challenge failure constraint",
}
_TYPE_KEYWORDS = {
    name: frozenset(SparseTokenizer().tokenize(query))
    for name, query in _TYPE_QUERIES.items()
}
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    id: str
    type: str
    status: RequirementStatus
    query: str
    covered_chunk_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str | list[str]]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "query": self.query,
            "covered_chunk_ids": list(self.covered_chunk_ids),
        }


def infer_evidence_requirements(question: str) -> tuple[EvidenceRequirement, ...]:
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("question must not be empty")
    words = set(SparseTokenizer().tokenize(normalized_question))
    detected: list[str] = []
    if words.intersection({"method", "methods", "approach", "procedure", "algorithm", "technique", "strategy"}) or any(
        cue in normalized_question.casefold()
        for cue in ("how did", "how does", "how was", "how were")
    ):
        detected.append("method")
    if words.intersection(
        {"result", "results", "finding", "findings", "outcome", "effect", "performance", "accuracy", "improve", "improved", "impact"}
    ):
        detected.append("result")
    if words.intersection(
        {"dataset", "data", "sample", "samples", "participant", "participants", "corpus"}
    ):
        detected.append("data")
    if words.intersection({"why", "reason", "reasons", "cause", "causes"}):
        detected.append("rationale")
    if words.intersection(
        {"limitation", "limitations", "weakness", "weaknesses", "challenge", "challenges"}
    ):
        detected.append("limitation")
    if not detected:
        detected.append("answer")

    requirements: list[EvidenceRequirement] = []
    for index, requirement_type in enumerate(dict.fromkeys(detected), start=1):
        suffix = _TYPE_QUERIES.get(requirement_type, "")
        retrieval_query = " ".join(part for part in (normalized_question, suffix) if part)
        requirements.append(
            EvidenceRequirement(
                id=f"r{index}",
                type=requirement_type,
                status="missing",
                query=retrieval_query,
            )
        )
    return tuple(requirements)


def assess_evidence_requirements(
    requirements: tuple[EvidenceRequirement, ...],
    candidates: tuple[RetrievalCandidate, ...] | list[RetrievalCandidate],
) -> tuple[EvidenceRequirement, ...]:
    tokenizer = SparseTokenizer()
    assessed: list[EvidenceRequirement] = []
    for requirement in requirements:
        covered_chunk_ids: list[str] = []
        if requirement.type == "answer":
            query_terms = {
                item
                for item in tokenizer.tokenize(requirement.query)
                if item not in _STOP_WORDS and len(item) > 1
            }
        else:
            query_terms = set(_TYPE_KEYWORDS.get(requirement.type, ()))
        for candidate in candidates:
            searchable_text = " ".join(
                (
                    candidate.chunk.text,
                    candidate.chunk.section_heading,
                    " ".join(candidate.chunk.section_path),
                )
            )
            candidate_terms = set(tokenizer.tokenize(searchable_text))
            if requirement.type == "answer":
                covered = bool(query_terms) and (
                    len(query_terms.intersection(candidate_terms))
                    / len(query_terms)
                    >= 0.2
                )
            else:
                covered = bool(query_terms.intersection(candidate_terms))
            if covered:
                covered_chunk_ids.append(candidate.chunk.chunk_id)
        assessed.append(
            replace(
                requirement,
                status="covered" if covered_chunk_ids else "missing",
                covered_chunk_ids=tuple(dict.fromkeys(covered_chunk_ids)),
            )
        )
    return tuple(assessed)


def evidence_requirement_coverage(
    requirements: tuple[EvidenceRequirement, ...],
) -> float:
    if not requirements:
        return 0.0
    return sum(item.status == "covered" for item in requirements) / len(requirements)


__all__ = [
    "EvidenceRequirement",
    "RequirementStatus",
    "assess_evidence_requirements",
    "evidence_requirement_coverage",
    "infer_evidence_requirements",
]
