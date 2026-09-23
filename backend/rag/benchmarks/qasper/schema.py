from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QasperParagraph:
    paragraph_id: str
    global_index: int
    section_index: int
    section_name: str
    paragraph_index: int
    text: str


@dataclass(frozen=True, slots=True)
class QasperSection:
    name: str
    section_index: int
    paragraphs: tuple[QasperParagraph, ...]


@dataclass(frozen=True, slots=True)
class QasperAnswer:
    annotation_id: str
    answer_type: str
    extractive_spans: tuple[str, ...]
    free_form_answer: str
    yes_no: bool | None
    unanswerable: bool
    evidence_texts: tuple[str, ...]
    highlighted_evidence: tuple[str, ...]

    @property
    def answer_text(self) -> str:
        if self.unanswerable or self.answer_type == "none":
            return "Unanswerable"
        if self.extractive_spans:
            return ", ".join(self.extractive_spans)
        if self.free_form_answer:
            return self.free_form_answer
        if self.yes_no is not None:
            return "Yes" if self.yes_no else "No"
        return ""


@dataclass(frozen=True, slots=True)
class QasperQuestion:
    question_id: str
    paper_id: str
    question: str
    answers: tuple[QasperAnswer, ...]


@dataclass(frozen=True, slots=True)
class QasperPaper:
    paper_id: str
    title: str
    abstract: str
    sections: tuple[QasperSection, ...]
    question_ids: tuple[str, ...]

    @property
    def paragraphs(self) -> tuple[QasperParagraph, ...]:
        return tuple(paragraph for section in self.sections for paragraph in section.paragraphs)


@dataclass(frozen=True, slots=True)
class QasperDataset:
    dataset_version: str
    split: str
    papers: dict[str, QasperPaper]
    questions: tuple[QasperQuestion, ...]
    source_path: str
    source_sha256: str


__all__ = [
    "QasperAnswer",
    "QasperDataset",
    "QasperPaper",
    "QasperParagraph",
    "QasperQuestion",
    "QasperSection",
]
