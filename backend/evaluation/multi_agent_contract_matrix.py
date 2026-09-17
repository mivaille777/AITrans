from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
)
from backend.evaluation.multi_agent_benchmark import (
    BenchmarkBudget,
    BenchmarkObservation,
    BenchmarkVersionInfo,
    MultiAgentBenchmarkReport,
    load_multi_agent_evaluation_cases,
    run_multi_agent_benchmark,
    write_multi_agent_benchmark_report,
)


def load_contract_evidence(path: str | Path) -> dict[str, dict[str, tuple[str, ...]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "ma10-contract-evidence-v1":
        raise ValueError("unsupported MA10 contract evidence schema")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, dict):
        raise TypeError("MA10 contract evidence requires a cases object")
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for case_id, raw in raw_cases.items():
        if not isinstance(raw, dict):
            raise TypeError(f"invalid contract evidence for {case_id}")
        pytest_selectors = tuple(str(item) for item in raw.get("pytest", ()) if str(item))
        vitest_files = tuple(str(item) for item in raw.get("vitest", ()) if str(item))
        if not pytest_selectors and not vitest_files:
            raise ValueError(f"contract evidence for {case_id} is empty")
        result[str(case_id)] = {
            "pytest": pytest_selectors,
            "vitest": vitest_files,
        }
    return result


def validate_contract_evidence(
    *, cases_path: str | Path, evidence_path: str | Path
) -> tuple[str, ...]:
    expected = {case.case_id for case in load_multi_agent_evaluation_cases(cases_path)}
    actual = set(load_contract_evidence(evidence_path))
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"contract evidence mismatch: missing={missing}, extra={extra}")
    return tuple(sorted(actual))


def _run(command: Sequence[str], *, cwd: Path) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode != 0:
        raise RuntimeError(
            f"contract evidence command failed ({completed.returncode}): "
            + " ".join(command)
        )
    return elapsed_ms, completed.stdout


def _pytest_durations(path: Path) -> dict[str, float]:
    root = ET.parse(path).getroot()
    durations: dict[str, float] = {}
    for item in root.iter("testcase"):
        name = str(item.attrib.get("name", ""))
        durations[name] = durations.get(name, 0.0) + float(
            item.attrib.get("time", 0.0) or 0.0
        ) * 1000
    return durations


def _selector_name(selector: str) -> str:
    return selector.rsplit("::", 1)[-1].split("[", 1)[0]


def _git_value(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def run_deterministic_contract_matrix(
    *,
    repository_root: str | Path,
    cases_path: str | Path,
    evidence_path: str | Path,
    output_path: str | Path,
) -> MultiAgentBenchmarkReport:
    root = Path(repository_root).resolve()
    cases = load_multi_agent_evaluation_cases(cases_path)
    evidence = load_contract_evidence(evidence_path)
    validate_contract_evidence(cases_path=cases_path, evidence_path=evidence_path)
    pytest_selectors = sorted(
        {selector for item in evidence.values() for selector in item["pytest"]}
    )
    vitest_files = sorted(
        {filename for item in evidence.values() for filename in item["vitest"]}
    )

    with tempfile.TemporaryDirectory(prefix="aitrans-ma10-") as temporary:
        junit_path = Path(temporary) / "pytest.xml"
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                *pytest_selectors,
                "-q",
                f"--junitxml={junit_path}",
            ],
            cwd=root,
        )
        durations = _pytest_durations(junit_path)
        vitest_elapsed = 0.0
        if vitest_files:
            npx = shutil.which("npx")
            if npx is None:
                raise RuntimeError("npx is required for MA10 frontend contract evidence")
            vitest_elapsed, _ = _run(
                [npx, "vitest", "run", *vitest_files],
                cwd=root / "apps" / "desktop",
            )

    commit = _git_value(root, "rev-parse", "HEAD")
    dirty = bool(_git_value(root, "status", "--porcelain"))
    observations: dict[str, BenchmarkObservation] = {}
    vitest_case_count = sum(bool(item["vitest"]) for item in evidence.values()) or 1
    for case in cases:
        selectors = evidence[case.case_id]["pytest"]
        frontend = evidence[case.case_id]["vitest"]
        latency_ms = sum(durations.get(_selector_name(item), 0.0) for item in selectors)
        if frontend:
            latency_ms += vitest_elapsed / vitest_case_count
        observations[case.case_id] = BenchmarkObservation(
            completed=True,
            dimension_scores={
                dimension: 1.0
                for dimension in case.score_dimensions
                if dimension not in {"latency", "cost"}
            },
            hard_assertion_results={assertion: True for assertion in case.hard_assertions},
            source_coverage=1.0 if "source_support" in case.score_dimensions else None,
            latency_ms=round(latency_ms, 3),
            versions=BenchmarkVersionInfo(
                git_commit=commit,
                graph_version=CURRENT_AGENT_GRAPH_VERSION,
                schema_version=str(CURRENT_AGENT_STATE_SCHEMA_VERSION),
                model_provider="deterministic-contract",
                model_name="no-model",
                model_version="not-applicable",
                retrieval_version="test-fixtures-v1",
            ),
            metadata={
                "measurement_scope": "deterministic_contract",
                "pytest_selectors": list(selectors),
                "vitest_files": list(frontend),
                "usage_measurement": "not_applicable_no_model",
                "cost_score_measurement": "not_measured",
                "production_latency_measurement": "not_measured",
                "semantic_quality_measurement": "not_measured",
            },
        )

    def runner(case, **_kwargs):
        return observations[case.case_id]

    report = run_multi_agent_benchmark(
        cases,
        runner=runner,
        environment="deterministic",
        production_budgets={
            "multi_agent": BenchmarkBudget(
                mode="production",
                deadline_ms=120_000,
            )
        },
        equal_token_limit=1,
        strategies=("multi_agent",),
        budget_modes=("production",),
        unverified_surfaces=(
            "qwen3_local",
            "configured_llm",
            "manual_ui",
            "semantic_quality_ab",
        ),
        metadata={
            "evidence_schema": "ma10-contract-evidence-v1",
            "candidate_hard_gate_passed": True,
            "working_tree_dirty": dirty,
            "usage_values": "null means unavailable; zero is never imputed",
        },
    )
    write_multi_agent_benchmark_report(report, output_path)
    return report


__all__ = [
    "load_contract_evidence",
    "run_deterministic_contract_matrix",
    "validate_contract_evidence",
]
