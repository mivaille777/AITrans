"""QASPER dataset support for the existing AITrans RAG pipeline."""

from backend.rag.benchmarks.qasper.adapter import (
    QasperAdaptedPaper,
    QasperParagraphSpan,
    adapt_qasper_paper,
)
from backend.rag.benchmarks.qasper.alignment import (
    AlignedAnswerEvidence,
    AlignmentError,
    QasperAlignment,
    align_qasper_evidence,
)
from backend.rag.benchmarks.qasper.loader import (
    download_qasper_split,
    load_qasper,
)
from backend.rag.benchmarks.qasper.schema import (
    QasperAnswer,
    QasperDataset,
    QasperPaper,
    QasperParagraph,
    QasperQuestion,
    QasperSection,
)

__all__ = [
    "AlignedAnswerEvidence",
    "AlignmentError",
    "QasperAdaptedPaper",
    "QasperAlignment",
    "QasperAnswer",
    "QasperDataset",
    "QasperPaper",
    "QasperParagraph",
    "QasperParagraphSpan",
    "QasperQuestion",
    "QasperSection",
    "adapt_qasper_paper",
    "align_qasper_evidence",
    "download_qasper_split",
    "load_qasper",
]
