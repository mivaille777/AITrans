from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from backend.rag.benchmarks.qasper.schema import QasperDataset
from backend.rag.chunking import CHUNKER_VERSION
from backend.rag.config import RagConfig

QASPER_ADAPTER_VERSION = "qasper-v0.3"


def qasper_sample_hash(dataset: QasperDataset) -> str:
    """Hash the selected papers and question IDs independently of answer order."""

    sample = {
        "questions": [
            {
                "question_id": question.question_id,
                "paper_id": question.paper_id,
                "question": question.question,
                "answers": [
                    {
                        "annotation_id": answer.annotation_id,
                        "answer_type": answer.answer_type,
                        "extractive_spans": answer.extractive_spans,
                        "free_form_answer": answer.free_form_answer,
                        "yes_no": answer.yes_no,
                        "unanswerable": answer.unanswerable,
                        "evidence_texts": answer.evidence_texts,
                        "highlighted_evidence": answer.highlighted_evidence,
                    }
                    for answer in question.answers
                ],
            }
            for question in dataset.questions
        ],
        "papers": [
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "sections": [
                    {
                        "name": section.name,
                        "paragraphs": [paragraph.text for paragraph in section.paragraphs],
                    }
                    for section in paper.sections
                ],
            }
            for paper in sorted(dataset.papers.values(), key=lambda item: item.paper_id)
        ],
    }
    encoded = json.dumps(
        sample,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IndexCacheFingerprint:
    dataset: str
    dataset_version: str
    split: str
    sample_hash: str
    parser_version: str
    chunker_version: str
    chunking_config: dict[str, object]
    semantic_chunking_config: dict[str, object]
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "dataset_version": self.dataset_version,
            "split": self.split,
            "sample_hash": self.sample_hash,
            "parser_version": self.parser_version,
            "chunker_version": self.chunker_version,
            "chunking_config": self.chunking_config,
            "semantic_chunking_config": self.semantic_chunking_config,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def build_index_cache_fingerprint(
    dataset: QasperDataset,
    config: RagConfig,
    *,
    chunker_version: str = CHUNKER_VERSION,
    parser_version: str = QASPER_ADAPTER_VERSION,
) -> IndexCacheFingerprint:
    """Fingerprint only inputs that change parsed chunks or dense vectors.

    Retrieval top-k, fusion, reranking, Small-to-Big, query planning, and
    evidence gating are intentionally excluded so query-time ablations share
    the same index and embeddings.
    """

    return IndexCacheFingerprint(
        dataset="qasper",
        dataset_version=dataset.dataset_version,
        split=dataset.split,
        sample_hash=qasper_sample_hash(dataset),
        parser_version=parser_version,
        chunker_version=chunker_version,
        chunking_config=config.chunking.model_dump(mode="json"),
        semantic_chunking_config=config.semantic_chunking.model_dump(mode="json"),
        embedding_provider=config.embedding.provider,
        embedding_model=config.embedding.model,
        embedding_dimension=config.embedding.dimension,
    )


__all__ = [
    "QASPER_ADAPTER_VERSION",
    "IndexCacheFingerprint",
    "build_index_cache_fingerprint",
    "qasper_sample_hash",
]
