from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.qasper.adapter import adapt_qasper_paper
from backend.rag.benchmarks.qasper.alignment import align_qasper_evidence
from backend.rag.benchmarks.qasper.loader import download_qasper_split, load_qasper
from backend.rag.benchmarks.qasper.schema import QasperDataset


def _write_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, payload)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    _atomic_write(path, payload)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _sample_dataset(dataset: QasperDataset, *, limit: int | None, seed: int) -> QasperDataset:
    if limit is None:
        return dataset
    if limit <= 0:
        raise ValueError("limit must be positive")
    selected = dataset.questions
    if limit < len(selected):
        chosen = set(random.Random(seed).sample(range(len(selected)), limit))
        selected = tuple(
            question for index, question in enumerate(dataset.questions) if index in chosen
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


def prepare_dataset(
    *,
    root: Path,
    split: str = "validation",
    raw_json: Path | None = None,
    limit: int | None = None,
    seed: int = 42,
    redownload: bool = False,
) -> dict[str, Any]:
    root = root.expanduser().resolve()
    raw_path = raw_json.expanduser().resolve() if raw_json else download_qasper_split(
        split,
        root / "raw",
        manifest_directory=root / "manifests",
        redownload=redownload,
    )
    dataset = _sample_dataset(load_qasper(raw_path, split=split), limit=limit, seed=seed)
    alignment = align_qasper_evidence(dataset)

    normalized_records: list[dict[str, Any]] = []
    for paper in dataset.papers.values():
        adapted = adapt_qasper_paper(paper, split=dataset.split)
        normalized_records.append(
            {
                "paper_id": paper.paper_id,
                "document": adapted.document.model_dump(mode="json"),
                "paragraphs": [
                    {
                        "paragraph_id": paragraph.paragraph_id,
                        "global_index": paragraph.global_index,
                        "section_name": paragraph.section_name,
                        "text": paragraph.text,
                        "start_char": paragraph.start_char,
                        "end_char": paragraph.end_char,
                    }
                    for paragraph in adapted.paragraphs
                ],
            }
        )

    qrels_records: list[dict[str, Any]] = []
    for question in dataset.questions:
        aligned_answers = alignment.by_question[question.question_id]
        qrels_records.append(
            {
                "question_id": question.question_id,
                "paper_id": question.paper_id,
                "question": question.question,
                "expected_retrieval": True,
                "no_answer": bool(question.answers)
                and all(answer.unanswerable for answer in question.answers),
                "answers": [
                    {
                        "annotation_id": answer.annotation_id,
                        "answer_type": answer.answer_type,
                        "answer": answer.answer_text,
                        "extractive_spans": list(answer.extractive_spans),
                        "free_form_answer": answer.free_form_answer,
                        "yes_no": answer.yes_no,
                        "evidence_texts": list(answer.evidence_texts),
                        "highlighted_evidence": list(answer.highlighted_evidence),
                        "evidence_paragraph_ids": list(aligned.paragraph_ids),
                        "evidence_complete": aligned.evidence_complete,
                    }
                    for answer, aligned in zip(question.answers, aligned_answers, strict=True)
                ],
                "gold_evidence_paragraph_ids": sorted(
                    {
                        paragraph_id
                        for answer in aligned_answers
                        for paragraph_id in answer.paragraph_ids
                    }
                ),
            }
        )

    split_root = root / "normalized" / dataset.split
    _write_jsonl(split_root / "papers.jsonl", normalized_records)
    _write_jsonl(root / "qrels" / f"{dataset.split}.jsonl", qrels_records)
    _write_jsonl(
        root / "alignment_errors" / f"{dataset.split}.jsonl",
        [asdict(error) for error in alignment.errors],
    )

    sample_hash = hashlib.sha256(
        "\n".join(question.question_id for question in dataset.questions).encode("utf-8")
    ).hexdigest()
    summary = {
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "source_split": "dev" if dataset.split == "validation" else dataset.split,
        "source_path": str(raw_path),
        "source_sha256": dataset.source_sha256,
        "sample_sha256": sample_hash,
        "seed": seed,
        "limit": limit,
        "paper_count": len(dataset.papers),
        "question_count": len(dataset.questions),
        "answer_annotation_count": sum(len(question.answers) for question in dataset.questions),
        "evidence_item_count": alignment.total_evidence_items,
        "aligned_evidence_item_count": alignment.aligned_evidence_items,
        "text_evidence_item_count": alignment.total_text_evidence_items,
        "aligned_text_evidence_item_count": alignment.aligned_text_evidence_items,
        "alignment_coverage": alignment.text_coverage,
        "overall_alignment_coverage": alignment.coverage,
        "alignment_target": 0.995,
        "alignment_target_met": alignment.text_coverage >= 0.995,
        "alignment_error_count": len(alignment.errors),
        "alignment_error_counts": dict(
            sorted(Counter(error.reason for error in alignment.errors).items())
        ),
        "prepared_files": {
            "normalized_papers": str(split_root / "papers.jsonl"),
            "qrels": str(root / "qrels" / f"{dataset.split}.jsonl"),
            "alignment_errors": str(root / "alignment_errors" / f"{dataset.split}.jsonl"),
        },
    }
    manifest_path = root / "manifests" / f"qasper-{dataset.split}-prepared.json"
    _write_json(manifest_path, summary)
    return {**summary, "manifest": str(manifest_path)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the official QASPER v0.3 dataset.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="download, adapt, and align a dataset split")
    prepare.add_argument("--split", choices=("validation", "dev", "train"), default="validation")
    prepare.add_argument("--root", type=Path, default=Path("data/benchmarks/qasper"))
    prepare.add_argument("--raw-json", type=Path)
    prepare.add_argument("--limit", type=int)
    prepare.add_argument("--seed", type=int, default=42)
    prepare.add_argument("--redownload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        summary = prepare_dataset(
            root=args.root,
            split=args.split,
            raw_json=args.raw_json,
            limit=args.limit,
            seed=args.seed,
            redownload=args.redownload,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["alignment_target_met"] else 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
