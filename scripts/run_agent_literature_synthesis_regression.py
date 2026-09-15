from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.evaluation.agent_literature_synthesis_benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 20.1 Agent literature synthesis regression.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    args = parser.parse_args()

    report = run_benchmark()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
