from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.evaluation.evidence_review_benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 20 Evidence Review regression benchmark.")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    print(payload)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["failed"] == 0 and report["case_count"] >= 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
