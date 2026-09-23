from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.benchmarks.qasper.loader import load_qasper
from backend.rag.benchmarks.qasper.sampling import sample_qasper_dataset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze deterministic Smoke20, Dev100, and complementary Holdout905 QASPER IDs."
    )
    parser.add_argument(
        "--raw-json",
        type=Path,
        default=Path("data/benchmarks/qasper/raw/qasper-dev-v0.3.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/rag/benchmarks/qasper/sample_ids"),
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset = load_qasper(args.raw_json, split="validation")
    smoke = sample_qasper_dataset(dataset, limit=20, seed=args.seed)
    dev = sample_qasper_dataset(dataset, limit=100, seed=args.seed)
    dev_ids = {question.question_id for question in dev.questions}
    holdout = sample_qasper_dataset(
        dataset,
        limit=None,
        seed=args.seed,
        question_ids=[
            question.question_id
            for question in dataset.questions
            if question.question_id not in dev_ids
        ],
    )
    samples = {
        f"validation-smoke20-seed{args.seed}.txt": smoke.questions,
        f"validation-dev100-seed{args.seed}.txt": dev.questions,
        f"validation-holdout905-after-dev100-seed{args.seed}.txt": holdout.questions,
    }
    if dev_ids & {question.question_id for question in holdout.questions}:
        raise RuntimeError("Dev100 and Holdout overlap")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample_manifest: dict[str, object] = {
        "dataset": "qasper",
        "dataset_version": dataset.dataset_version,
        "split": dataset.split,
        "source_sha256": dataset.source_sha256,
        "seed": args.seed,
        "selection_algorithm": "random.Random(seed).sample(dataset question indexes), restored to source order; holdout is the Dev100 complement",
        "smoke20_dev100_overlap_count": len(
            {question.question_id for question in smoke.questions} & dev_ids
        ),
        "samples": {},
    }
    sample_records: dict[str, dict[str, object]] = {}
    for filename, questions in samples.items():
        ids = [question.question_id for question in questions]
        payload = "".join(f"{question_id}\n" for question_id in ids).encode("utf-8")
        path = args.output_dir / filename
        path.write_bytes(payload)
        sample_records[filename] = {
            "question_count": len(ids),
            "file_sha256": hashlib.sha256(payload).hexdigest(),
            "question_ids_sha256": hashlib.sha256(payload).hexdigest(),
            "answer_type_counts": _answer_type_counts(questions),
        }
    sample_manifest["samples"] = sample_records
    manifest_path = args.output_dir / f"validation-seed{args.seed}-manifest.json"
    manifest_path.write_text(
        json.dumps(sample_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": str(manifest_path), **sample_records}, ensure_ascii=False, indent=2))
    return 0


def _answer_type_counts(questions: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        for answer in question.answers:
            key = str(answer.answer_type)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
