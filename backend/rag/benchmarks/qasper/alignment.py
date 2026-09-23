from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

from backend.rag.benchmarks.qasper.schema import QasperDataset
from backend.rag.models import DocumentChunk

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class AlignedAnswerEvidence:
    annotation_id: str
    answer_type: str
    answer_text: str
    evidence_texts: tuple[str, ...]
    paragraph_ids: tuple[str, ...]
    evidence_complete: bool


@dataclass(frozen=True, slots=True)
class AlignmentError:
    paper_id: str
    question_id: str
    annotation_id: str
    evidence_index: int
    evidence_text: str
    reason: str


@dataclass(frozen=True, slots=True)
class QasperAlignment:
    by_question: dict[str, tuple[AlignedAnswerEvidence, ...]]
    errors: tuple[AlignmentError, ...]
    total_evidence_items: int
    aligned_evidence_items: int
    total_text_evidence_items: int
    aligned_text_evidence_items: int

    @property
    def coverage(self) -> float:
        if not self.total_evidence_items:
            return 1.0
        return self.aligned_evidence_items / self.total_evidence_items

    @property
    def text_coverage(self) -> float:
        if not self.total_text_evidence_items:
            return 1.0
        return self.aligned_text_evidence_items / self.total_text_evidence_items


def normalize_evidence_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(text))
    normalized = normalized.replace("\u00a0", " ")
    return _WHITESPACE.sub(" ", normalized).strip()


def _align_one(
    evidence_text: str,
    paragraph_index: dict[str, list[str]],
    normalized_paragraphs: list[tuple[str, str]],
    section_index: dict[str, list[str]],
) -> tuple[tuple[str, ...], str]:
    normalized = normalize_evidence_text(evidence_text)
    if not normalized:
        return (), "empty_evidence"
    if normalized.casefold().startswith("float selected:"):
        return (), "non_text_float_evidence"
    section_matches = section_index.get(normalized)
    if section_matches:
        return tuple(section_matches), "section_heading"
    exact = paragraph_index.get(normalized)
    if exact:
        return tuple(exact), "normalized_exact"
    if len(normalized) >= 32:
        matches = tuple(
            paragraph_id
            for paragraph_text, paragraph_id in normalized_paragraphs
            if normalized in paragraph_text or paragraph_text in normalized
        )
        if matches:
            return matches, "substring"
    return (), "no_paragraph_match"


def align_qasper_evidence(dataset: QasperDataset) -> QasperAlignment:
    """Resolve every annotator evidence string to stable QASPER paragraph IDs."""

    by_paper: dict[
        str,
        tuple[dict[str, list[str]], list[tuple[str, str]], dict[str, list[str]]],
    ] = {}
    for paper_id, paper in dataset.papers.items():
        exact: dict[str, list[str]] = {}
        normalized_paragraphs: list[tuple[str, str]] = []
        sections: dict[str, list[str]] = {}
        for paragraph in paper.paragraphs:
            normalized = normalize_evidence_text(paragraph.text)
            if not normalized:
                continue
            exact.setdefault(normalized, []).append(paragraph.paragraph_id)
            normalized_paragraphs.append((normalized, paragraph.paragraph_id))
            section_key = normalize_evidence_text(paragraph.section_name)
            if section_key:
                sections.setdefault(section_key, []).append(paragraph.paragraph_id)
        by_paper[paper_id] = (exact, normalized_paragraphs, sections)

    aligned_questions: dict[str, tuple[AlignedAnswerEvidence, ...]] = {}
    errors: list[AlignmentError] = []
    total = 0
    aligned = 0
    total_text = 0
    aligned_text = 0
    for question in dataset.questions:
        paper_index = by_paper.get(question.paper_id, ({}, [], {}))
        aligned_answers: list[AlignedAnswerEvidence] = []
        for answer in question.answers:
            paragraph_ids: list[str] = []
            unmatched_count = 0
            for evidence_index, evidence_text in enumerate(answer.evidence_texts):
                total += 1
                matches, reason = _align_one(
                    evidence_text,
                    paper_index[0],
                    paper_index[1],
                    paper_index[2],
                )
                is_text_evidence = reason != "non_text_float_evidence"
                if is_text_evidence:
                    total_text += 1
                if matches:
                    aligned += 1
                    if is_text_evidence:
                        aligned_text += 1
                    paragraph_ids.extend(matches)
                else:
                    unmatched_count += 1
                    errors.append(
                        AlignmentError(
                            paper_id=question.paper_id,
                            question_id=question.question_id,
                            annotation_id=answer.annotation_id,
                            evidence_index=evidence_index,
                            evidence_text=evidence_text,
                            reason=reason,
                        )
                    )
            aligned_answers.append(
                AlignedAnswerEvidence(
                    annotation_id=answer.annotation_id,
                    answer_type=answer.answer_type,
                    answer_text=answer.answer_text,
                    evidence_texts=answer.evidence_texts,
                    paragraph_ids=tuple(dict.fromkeys(paragraph_ids)),
                    evidence_complete=unmatched_count == 0,
                )
            )
        aligned_questions[question.question_id] = tuple(aligned_answers)
    return QasperAlignment(
        by_question=aligned_questions,
        errors=tuple(errors),
        total_evidence_items=total,
        aligned_evidence_items=aligned,
        total_text_evidence_items=total_text,
        aligned_text_evidence_items=aligned_text,
    )


def map_paragraphs_to_chunks(
    chunks: list[DocumentChunk],
) -> dict[str, tuple[str, ...]]:
    """Build the current chunking variant's paragraph-to-chunk projection."""

    paragraph_chunks: dict[str, list[str]] = {}
    for chunk in chunks:
        benchmark_metadata = chunk.metadata.get("benchmark")
        if not isinstance(benchmark_metadata, dict):
            continue
        paragraph_ids = benchmark_metadata.get("source_paragraph_ids", [])
        if not isinstance(paragraph_ids, list):
            continue
        for paragraph_id in paragraph_ids:
            if not isinstance(paragraph_id, str) or not paragraph_id:
                continue
            paragraph_chunks.setdefault(paragraph_id, []).append(chunk.chunk_id)
    return {
        paragraph_id: tuple(dict.fromkeys(chunk_ids))
        for paragraph_id, chunk_ids in paragraph_chunks.items()
    }


def map_gold_paragraphs_to_chunks(
    paragraph_ids: list[str] | tuple[str, ...],
    chunks: list[DocumentChunk],
) -> tuple[str, ...]:
    """Resolve stable gold paragraph IDs into chunk IDs for one index variant."""

    paragraph_chunks = map_paragraphs_to_chunks(chunks)
    selected: list[str] = []
    for paragraph_id in paragraph_ids:
        selected.extend(paragraph_chunks.get(paragraph_id, ()))
    return tuple(dict.fromkeys(selected))


__all__ = [
    "AlignedAnswerEvidence",
    "AlignmentError",
    "QasperAlignment",
    "align_qasper_evidence",
    "map_gold_paragraphs_to_chunks",
    "map_paragraphs_to_chunks",
    "normalize_evidence_text",
]
