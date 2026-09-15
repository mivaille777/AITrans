from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.rag.evaluation import evaluate_rag
from backend.rag.evaluation_dataset import (
    load_evaluation_dataset,
    load_evaluation_predictions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate deterministic RAG retrieval, reranking, citation, and latency "
            "predictions against a human-annotated JSON/JSONL dataset."
        )
    )
    parser.add_argument(
        "--dataset", required=True, help="Evaluation JSON or JSONL path."
    )
    parser.add_argument(
        "--predictions", required=True, help="Prediction JSON or JSONL path."
    )
    parser.add_argument("--output", default="", help="Optional JSON report path.")
    parser.add_argument(
        "--fail-below-recall-at-10",
        type=float,
        default=None,
        metavar="RATE",
        help="Return exit code 2 when Recall@10 is below RATE.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_evaluation_dataset(args.dataset)
    predictions = load_evaluation_predictions(args.predictions)
    report = evaluate_rag(cases, predictions)
    rendered = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    threshold = args.fail_below_recall_at_10
    if threshold is not None and report.retrieval.recall_at_10 < threshold:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
