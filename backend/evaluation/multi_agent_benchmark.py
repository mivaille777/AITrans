from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Mapping, Protocol, Sequence

BenchmarkStrategy = Literal["single_agent", "legacy_collaboration", "multi_agent"]
BenchmarkEnvironment = Literal["deterministic", "qwen3_local", "configured_llm", "manual_ui"]
BenchmarkBudgetMode = Literal["production", "equal_token"]

RELEASE_BLOCKER_CODES = frozenset(
    {
        "scope_leak",
        "fabricated_experiment",
        "fabricated_reference",
        "silent_note_overwrite",
        "deleted_data_resurrection",
        "duplicate_business_write",
    }
)


@dataclass(frozen=True, slots=True)
class MultiAgentBenchmarkCase:
    case_id: str
    split: str
    stages: tuple[str, ...]
    category: str
    prompt: str
    fixture_refs: tuple[str, ...]
    hard_assertions: tuple[str, ...]
    score_dimensions: tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True, slots=True)
class BenchmarkBudget:
    mode: BenchmarkBudgetMode
    token_limit: int = 0
    model_call_limit: int = 0
    tool_call_limit: int = 0
    retrieval_call_limit: int = 0
    deadline_ms: int = 0

    def __post_init__(self) -> None:
        for name in ("token_limit", "model_call_limit", "tool_call_limit", "retrieval_call_limit", "deadline_ms"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True, slots=True)
class BenchmarkVersionInfo:
    git_commit: str = ""
    graph_version: str = ""
    schema_version: str = ""
    model_provider: str = ""
    model_name: str = ""
    model_version: str = ""
    retrieval_version: str = ""


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    """Measured output from one strategy run; quality is supplied, never inferred here."""

    completed: bool
    dimension_scores: Mapping[str, float] = field(default_factory=dict)
    hard_assertion_results: Mapping[str, bool] = field(default_factory=dict)
    source_coverage: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    retrieval_calls: int = 0
    latency_ms: float = 0.0
    degraded: bool = False
    degradation_reasons: tuple[str, ...] = ()
    failure_code: str = ""
    safety_violations: tuple[str, ...] = ()
    versions: BenchmarkVersionInfo = field(default_factory=BenchmarkVersionInfo)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("prompt_tokens", "completion_tokens", "model_calls", "tool_calls", "retrieval_calls"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if self.source_coverage is not None and not 0 <= self.source_coverage <= 1:
            raise ValueError("source_coverage must be between 0 and 1")
        if any(not 0 <= float(score) <= 1 for score in self.dimension_scores.values()):
            raise ValueError("dimension scores must be between 0 and 1")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class BenchmarkStrategyRunner(Protocol):
    def __call__(
        self,
        case: MultiAgentBenchmarkCase,
        *,
        strategy: BenchmarkStrategy,
        environment: BenchmarkEnvironment,
        budget: BenchmarkBudget,
    ) -> BenchmarkObservation: ...


@dataclass(frozen=True, slots=True)
class BenchmarkTaskResult:
    case_id: str
    split: str
    category: str
    strategy: BenchmarkStrategy
    environment: BenchmarkEnvironment
    budget: BenchmarkBudget
    completed: bool
    passed: bool
    dimension_scores: Mapping[str, float]
    hard_assertion_results: Mapping[str, bool]
    source_coverage: float | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_calls: int
    tool_calls: int
    retrieval_calls: int
    latency_ms: float
    degraded: bool
    degradation_reasons: tuple[str, ...]
    failure_code: str
    safety_violations: tuple[str, ...]
    release_blockers: tuple[str, ...]
    budget_violations: tuple[str, ...]
    versions: BenchmarkVersionInfo
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BenchmarkStrategySummary:
    strategy: BenchmarkStrategy
    environment: BenchmarkEnvironment
    budget_mode: BenchmarkBudgetMode
    case_count: int
    completed_count: int
    passed_count: int
    degraded_count: int
    release_blocker_count: int
    mean_source_coverage: float | None
    mean_total_tokens: float
    mean_model_calls: float
    mean_tool_calls: float
    mean_retrieval_calls: float
    mean_latency_ms: float
    mean_dimension_scores: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class MultiAgentBenchmarkReport:
    schema_version: str
    environment: BenchmarkEnvironment
    case_count: int
    strategies: tuple[BenchmarkStrategy, ...]
    budget_modes: tuple[BenchmarkBudgetMode, ...]
    tasks: tuple[BenchmarkTaskResult, ...]
    summaries: tuple[BenchmarkStrategySummary, ...]
    release_ready: bool
    release_blockers: tuple[str, ...]
    unverified_surfaces: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return _json_safe(asdict(self))  # type: ignore[return-value]

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def load_multi_agent_evaluation_cases(path: str | Path) -> tuple[MultiAgentBenchmarkCase, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("multi-agent evaluation cases must be a JSON array")
    result: list[MultiAgentBenchmarkCase] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("each multi-agent evaluation case must be an object")
        case_id = str(raw.get("case_id", "") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError(f"missing or duplicate case_id: {case_id!r}")
        seen.add(case_id)
        assertions = tuple(str(v) for v in raw.get("hard_assertions", ()) if str(v))
        dimensions = tuple(str(v) for v in raw.get("score_dimensions", ()) if str(v))
        if not assertions or not dimensions:
            raise ValueError(f"case {case_id} requires hard assertions and score dimensions")
        result.append(
            MultiAgentBenchmarkCase(
                case_id=case_id,
                split=str(raw.get("split", "") or ""),
                stages=tuple(str(v) for v in raw.get("stage", ()) if str(v)),
                category=str(raw.get("category", "") or ""),
                prompt=str(raw.get("prompt", "") or ""),
                fixture_refs=tuple(str(v) for v in raw.get("fixture_refs", ()) if str(v)),
                hard_assertions=assertions,
                score_dimensions=dimensions,
                notes=str(raw.get("notes", "") or ""),
            )
        )
    return tuple(result)


def _budget_violations(observation: BenchmarkObservation, budget: BenchmarkBudget) -> tuple[str, ...]:
    checks = (
        (budget.token_limit and observation.total_tokens > budget.token_limit, "token_budget_exceeded"),
        (budget.model_call_limit and observation.model_calls > budget.model_call_limit, "model_call_budget_exceeded"),
        (budget.tool_call_limit and observation.tool_calls > budget.tool_call_limit, "tool_call_budget_exceeded"),
        (budget.retrieval_call_limit and observation.retrieval_calls > budget.retrieval_call_limit, "retrieval_budget_exceeded"),
        (budget.deadline_ms and observation.latency_ms > budget.deadline_ms, "deadline_exceeded"),
    )
    return tuple(code for violated, code in checks if violated)


def _make_result(case: MultiAgentBenchmarkCase, strategy: BenchmarkStrategy, environment: BenchmarkEnvironment, budget: BenchmarkBudget, observation: BenchmarkObservation) -> BenchmarkTaskResult:
    assertions = {item: bool(observation.hard_assertion_results.get(item, False)) for item in case.hard_assertions}
    safety = tuple(sorted({str(v) for v in observation.safety_violations if str(v)}))
    blockers = tuple(v for v in safety if v in RELEASE_BLOCKER_CODES)
    budget_violations = _budget_violations(observation, budget)
    passed = bool(observation.completed and all(assertions.values()) and not blockers and not budget_violations and not observation.failure_code)
    return BenchmarkTaskResult(
        case_id=case.case_id, split=case.split, category=case.category, strategy=strategy,
        environment=environment, budget=budget, completed=observation.completed, passed=passed,
        dimension_scores={k: float(v) for k, v in observation.dimension_scores.items()},
        hard_assertion_results=assertions, source_coverage=observation.source_coverage,
        prompt_tokens=observation.prompt_tokens, completion_tokens=observation.completion_tokens,
        total_tokens=observation.total_tokens, model_calls=observation.model_calls,
        tool_calls=observation.tool_calls, retrieval_calls=observation.retrieval_calls,
        latency_ms=float(observation.latency_ms), degraded=observation.degraded,
        degradation_reasons=tuple(observation.degradation_reasons), failure_code=observation.failure_code,
        safety_violations=safety, release_blockers=blockers, budget_violations=budget_violations,
        versions=observation.versions, metadata=dict(observation.metadata),
    )


def _mean(values: Iterable[float]) -> float:
    frozen = tuple(values)
    return round(sum(frozen) / len(frozen), 6) if frozen else 0.0


def _summaries(tasks: Sequence[BenchmarkTaskResult]) -> tuple[BenchmarkStrategySummary, ...]:
    groups: dict[tuple[str, str, str], list[BenchmarkTaskResult]] = {}
    for task in tasks:
        groups.setdefault((task.strategy, task.environment, task.budget.mode), []).append(task)
    output: list[BenchmarkStrategySummary] = []
    for (strategy, environment, mode), items in sorted(groups.items()):
        dimensions = sorted({d for item in items for d in item.dimension_scores})
        coverages = [float(item.source_coverage) for item in items if item.source_coverage is not None]
        output.append(
            BenchmarkStrategySummary(
                strategy=strategy, environment=environment, budget_mode=mode,  # type: ignore[arg-type]
                case_count=len(items), completed_count=sum(v.completed for v in items),
                passed_count=sum(v.passed for v in items), degraded_count=sum(v.degraded for v in items),
                release_blocker_count=sum(bool(v.release_blockers) for v in items),
                mean_source_coverage=_mean(coverages) if coverages else None,
                mean_total_tokens=_mean(float(v.total_tokens) for v in items),
                mean_model_calls=_mean(float(v.model_calls) for v in items),
                mean_tool_calls=_mean(float(v.tool_calls) for v in items),
                mean_retrieval_calls=_mean(float(v.retrieval_calls) for v in items),
                mean_latency_ms=_mean(v.latency_ms for v in items),
                mean_dimension_scores={d: _mean(v.dimension_scores[d] for v in items if d in v.dimension_scores) for d in dimensions},
            )
        )
    return tuple(output)


def run_multi_agent_benchmark(
    cases: Iterable[MultiAgentBenchmarkCase], *, runner: BenchmarkStrategyRunner,
    environment: BenchmarkEnvironment, production_budgets: Mapping[BenchmarkStrategy, BenchmarkBudget],
    equal_token_limit: int,
    strategies: Sequence[BenchmarkStrategy] = ("single_agent", "legacy_collaboration", "multi_agent"),
    budget_modes: Sequence[BenchmarkBudgetMode] = ("production", "equal_token"),
    unverified_surfaces: Sequence[str] = (), metadata: Mapping[str, object] | None = None,
) -> MultiAgentBenchmarkReport:
    frozen_cases = tuple(cases)
    if not frozen_cases:
        raise ValueError("benchmark requires at least one case")
    if "equal_token" in budget_modes and equal_token_limit <= 0:
        raise ValueError("equal_token_limit must be > 0 when equal-token comparison is enabled")
    tasks: list[BenchmarkTaskResult] = []
    for mode in budget_modes:
        for strategy in strategies:
            source = production_budgets.get(strategy)
            if source is None:
                raise ValueError(f"missing production budget for strategy {strategy}")
            budget = BenchmarkBudget(
                mode=mode,
                token_limit=source.token_limit if mode == "production" else equal_token_limit,
                model_call_limit=source.model_call_limit, tool_call_limit=source.tool_call_limit,
                retrieval_call_limit=source.retrieval_call_limit, deadline_ms=source.deadline_ms,
            )
            for case in frozen_cases:
                observation = runner(case, strategy=strategy, environment=environment, budget=budget)
                tasks.append(_make_result(case, strategy, environment, budget, observation))
    blockers = tuple(sorted({f"{t.case_id}:{t.strategy}:{t.budget.mode}:{code}" for t in tasks for code in t.release_blockers}))
    unverified = tuple(unverified_surfaces)
    return MultiAgentBenchmarkReport(
        schema_version="ma10-benchmark-v1", environment=environment, case_count=len(frozen_cases),
        strategies=tuple(strategies), budget_modes=tuple(budget_modes), tasks=tuple(tasks),
        summaries=_summaries(tasks), release_ready=bool(tasks) and all(t.passed for t in tasks) and not blockers and not unverified,
        release_blockers=blockers, unverified_surfaces=unverified, metadata=dict(metadata or {}),
    )


def write_multi_agent_benchmark_report(report: MultiAgentBenchmarkReport, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.to_json() + "\n", encoding="utf-8")
    return destination


__all__ = [
    "BenchmarkBudget", "BenchmarkBudgetMode", "BenchmarkEnvironment", "BenchmarkObservation",
    "BenchmarkStrategy", "BenchmarkStrategyRunner", "BenchmarkTaskResult", "BenchmarkVersionInfo",
    "BenchmarkStrategySummary", "MultiAgentBenchmarkCase", "MultiAgentBenchmarkReport",
    "RELEASE_BLOCKER_CODES", "load_multi_agent_evaluation_cases", "run_multi_agent_benchmark",
    "write_multi_agent_benchmark_report",
]
