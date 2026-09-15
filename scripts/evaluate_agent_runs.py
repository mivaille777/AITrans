from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.evaluation.dataset import load_evaluation_dataset
from backend.evaluation.runner import evaluate_agent_batch
from backend.services.agent_trace_store_service import AgentTraceStoreService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate persisted Agent runs against deterministic final-state and "
            "trajectory reliability criteria."
        )
    )
    parser.add_argument(
        "--dataset",
        default="backend/evaluation/datasets/smoke.jsonl",
        help="JSONL file containing expected result and trajectory criteria.",
    )
    parser.add_argument(
        "--mapping",
        required=True,
        help="JSON object mapping evaluation case_id to persisted run_id.",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Optional path to agent_observability.sqlite3. Uses the app default when omitted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_evaluation_dataset(args.dataset)
    mapping_payload = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    if not isinstance(mapping_payload, dict):
        raise ValueError("--mapping must contain a JSON object of case_id -> run_id.")
    mapping = {str(key): str(value) for key, value in mapping_payload.items()}
    store = AgentTraceStoreService(storage_path=args.db or None)

    batch = evaluate_agent_batch(
        cases,
        resolve_run=lambda case: store.get_run(mapping.get(case.case_id, "")),
        resolve_events=lambda run: store.list_events(run.run_id),
    )
    print(json.dumps(asdict(batch), ensure_ascii=False, indent=2))
    return 0 if batch.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
