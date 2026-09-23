from __future__ import annotations

import random
from dataclasses import replace

from backend.rag.benchmarks.qasper.schema import QasperDataset


def sample_qasper_dataset(
    dataset: QasperDataset,
    *,
    limit: int | None,
    seed: int = 42,
) -> QasperDataset:
    """Select a reproducible question sample and retain only its papers."""

    if limit is None:
        return dataset
    if limit <= 0:
        raise ValueError("limit must be positive")
    selected = dataset.questions
    if limit < len(selected):
        chosen = set(random.Random(seed).sample(range(len(selected)), limit))
        selected = tuple(
            question
            for index, question in enumerate(dataset.questions)
            if index in chosen
        )
    paper_ids = {question.paper_id for question in selected}
    papers = {
        paper_id: replace(
            paper,
            question_ids=tuple(
                question.question_id
                for question in selected
                if question.paper_id == paper_id
            ),
        )
        for paper_id, paper in dataset.papers.items()
        if paper_id in paper_ids
    }
    return replace(dataset, papers=papers, questions=tuple(selected))


__all__ = ["sample_qasper_dataset"]
