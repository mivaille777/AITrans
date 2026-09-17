from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from backend.evaluation.multi_agent_contract_matrix import (
    run_deterministic_contract_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic MA10 T01-T36 contract matrix."
    )
    parser.add_argument(
        "--output",
        default="docs/development/ma10-deterministic-report.json",
    )
    arguments = parser.parse_args()
    root = _REPOSITORY_ROOT
    report = run_deterministic_contract_matrix(
        repository_root=root,
        cases_path=root / "tests" / "multi_agent" / "evaluation_cases.json",
        evidence_path=root / "tests" / "multi_agent" / "evaluation_evidence.json",
        output_path=root / arguments.output,
    )
    passed = sum(item.passed for item in report.tasks)
    print(
        f"MA10 deterministic contract matrix: {passed}/{len(report.tasks)} passed; "
        f"release_ready={report.release_ready}"
    )
    return 0 if passed == len(report.tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
