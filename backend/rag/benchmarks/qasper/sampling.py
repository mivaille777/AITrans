from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from backend.rag.benchmarks.qasper.schema import QasperDataset


def sample_qasper_dataset(
    dataset: QasperDataset,
    *,
    limit: int | None,
    seed: int = 42,
    question_ids: Sequence[str] | None = None,
) -> QasperDataset:
    """Select a reproducible question sample and retain only its papers."""

    if question_ids is not None:
        normalized_ids = tuple(str(value).strip() for value in question_ids)
        if not normalized_ids or any(not value for value in normalized_ids):
            raise ValueError("question_ids must contain non-empty IDs")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("question_ids must be unique")
        if limit is not None and len(normalized_ids) != limit:
            raise ValueError(
                f"question ID file contains {len(normalized_ids)} IDs, expected {limit} for this mode"
            )
        questions_by_id = {item.question_id: item for item in dataset.questions}
        missing_ids = [value for value in normalized_ids if value not in questions_by_id]
        if missing_ids:
            raise ValueError(
                "question IDs are absent from the selected QASPER split: "
                + ", ".join(missing_ids[:10])
            )
        selected_ids = set(normalized_ids)
        selected = tuple(
            question
            for question in dataset.questions
            if question.question_id in selected_ids
        )
    elif limit is None:
        selected = dataset.questions
    else:
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
    if len(selected) == len(dataset.questions) and selected is dataset.questions:
        return dataset
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


def read_question_ids_file(path: str | Path) -> tuple[tuple[str, ...], str]:
    """Read newline-delimited question IDs and return them with the file SHA256."""

    source = Path(path).expanduser().resolve()
    raw_bytes = source.read_bytes()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"question ID file must be UTF-8: {source}") from exc
    ids = tuple(line.strip() for line in text.splitlines() if line.strip())
    if not ids:
        raise ValueError(f"question ID file is empty: {source}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"question ID file contains duplicate IDs: {source}")
    return ids, hashlib.sha256(raw_bytes).hexdigest()


__all__ = ["read_question_ids_file", "sample_qasper_dataset"]
