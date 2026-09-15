from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Literal

from backend.agent_core.events import AgentEvent, AgentEventType
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_core.runtime import AgentRuntime
from backend.agent_core.state import AgentState
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.evaluation.agent_evaluator import AgentEvaluationExpectation
from backend.evaluation.dataset import load_evaluation_dataset
from backend.models.agent_react import AgentEvidenceGateAssessment, AgentReActDecision
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem, AgentRouteDecision
from backend.services.agent_tool_registry import AgentToolExecutionResult, AgentToolSpec
from backend.services.agent_trace_store_service import StoredAgentEvent, StoredAgentRun
from backend.services.product_agent_service import ProductAgentService

BenchmarkRouteKind = Literal["answer", "tool", "complex"]
BenchmarkFailureMode = Literal["none", "retry_once", "fail_all"]
_GROUNDED_TOOLS = frozenset({"search_knowledge_base", "search_research_notes"})
_WRITE_TOOLS = frozenset({"save_research_note", "update_research_note"})


@dataclass(frozen=True, slots=True)
class AgentLiveBenchmarkCase:
    expectation: AgentEvaluationExpectation
    category: str
    user_message: str
    route_kind: BenchmarkRouteKind
    react_tool_sequence: tuple[str, ...] = ()
    failure_mode: BenchmarkFailureMode = "none"
    failure_tool: str = ""
    gate_actions: tuple[str, ...] = ()
    verification_pass: bool = True
    verification_fallback: bool = False
    retrieval_fallback: bool = False
    confirmed_write_tools: tuple[str, ...] = ()
    context_chars: int = 0
    max_react_iterations: int = 0
    max_tool_calls: int = 0
    max_knowledge_searches: int = 0
    reported_prompt_tokens: int = 0
    reported_completion_tokens: int = 0

    @property
    def case_id(self) -> str:
        return self.expectation.case_id

    @property
    def route_tool(self) -> str:
        if self.route_kind != "tool":
            return ""
        return self.expectation.expected_tool_name


@dataclass(frozen=True, slots=True)
class AgentLiveBenchmarkExecution:
    case_id: str
    category: str
    run: StoredAgentRun
    events: tuple[StoredAgentEvent, ...]


@dataclass(frozen=True, slots=True)
class AgentLiveBenchmarkSuite:
    cases: tuple[AgentLiveBenchmarkCase, ...]
    executions: tuple[AgentLiveBenchmarkExecution, ...]

    def get_run(self, case_id: str) -> StoredAgentRun | None:
        item = next((item for item in self.executions if item.case_id == case_id), None)
        return item.run if item is not None else None

    def get_events(self, run: StoredAgentRun) -> tuple[StoredAgentEvent, ...]:
        item = next(
            (item for item in self.executions if item.run.run_id == run.run_id),
            None,
        )
        return item.events if item is not None else ()

    @property
    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.category] = counts.get(case.category, 0) + 1
        return dict(sorted(counts.items()))


def _case_payloads(path: str | Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Benchmark case line {line_number} must be an object.")
        case_id = str(payload.get("case_id", "") or "").strip()
        if not case_id:
            raise ValueError(f"Benchmark case line {line_number} is missing case_id.")
        if case_id in result:
            raise ValueError(f"Duplicate benchmark case_id: {case_id}")
        result[case_id] = payload
    return result


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def load_live_benchmark_cases(path: str | Path) -> tuple[AgentLiveBenchmarkCase, ...]:
    expectations = load_evaluation_dataset(path)
    payloads = _case_payloads(path)
    cases: list[AgentLiveBenchmarkCase] = []
    for expectation in expectations:
        payload = payloads[expectation.case_id]
        category = str(payload.get("category", "") or "").strip().lower()
        if not category:
            raise ValueError(f"Benchmark case {expectation.case_id!r} requires category.")
        route_kind = str(payload.get("route_kind", "") or "").strip().lower()
        if route_kind not in {"answer", "tool", "complex"}:
            route_kind = "complex" if expectation.expect_react else (
                "tool" if expectation.expected_tool_name else "answer"
            )
        failure_mode = str(payload.get("failure_mode", "none") or "none").strip().lower()
        if failure_mode not in {"none", "retry_once", "fail_all"}:
            raise ValueError(
                f"Benchmark case {expectation.case_id!r} has invalid failure_mode."
            )
        cases.append(
            AgentLiveBenchmarkCase(
                expectation=expectation,
                category=category,
                user_message=str(
                    payload.get("user_message", expectation.case_id) or expectation.case_id
                ),
                route_kind=route_kind,  # type: ignore[arg-type]
                react_tool_sequence=(
                    _string_tuple(payload.get("react_tool_sequence"))
                    or expectation.expected_tool_sequence
                ),
                failure_mode=failure_mode,  # type: ignore[arg-type]
                failure_tool=str(payload.get("failure_tool", "") or "").strip(),
                gate_actions=_string_tuple(payload.get("gate_actions")),
                verification_pass=bool(payload.get("verification_pass", True)),
                verification_fallback=bool(payload.get("verification_fallback", False)),
                retrieval_fallback=bool(payload.get("retrieval_fallback", False)),
                confirmed_write_tools=_string_tuple(payload.get("confirmed_write_tools")),
                context_chars=max(0, int(payload.get("context_chars", 0) or 0)),
                max_react_iterations=max(
                    0, int(payload.get("policy_max_react_iterations", 0) or 0)
                ),
                max_tool_calls=max(0, int(payload.get("policy_max_tool_calls", 0) or 0)),
                max_knowledge_searches=max(
                    0, int(payload.get("policy_max_knowledge_searches", 0) or 0)
                ),
                reported_prompt_tokens=max(
                    0, int(payload.get("reported_prompt_tokens", 0) or 0)
                ),
                reported_completion_tokens=max(
                    0, int(payload.get("reported_completion_tokens", 0) or 0)
                ),
            )
        )
    return tuple(cases)


def validate_live_benchmark_coverage(
    cases: Iterable[AgentLiveBenchmarkCase],
    *,
    minimum_cases: int = 30,
    maximum_cases: int = 50,
) -> dict[str, int]:
    frozen = tuple(cases)
    if not minimum_cases <= len(frozen) <= maximum_cases:
        raise ValueError(
            f"Stage 14 benchmark requires {minimum_cases}-{maximum_cases} cases; "
            f"found {len(frozen)}."
        )
    counts: dict[str, int] = {}
    for case in frozen:
        counts[case.category] = counts.get(case.category, 0) + 1
    required = {
        "translation",
        "reading",
        "summarization",
        "research",
        "multi_step",
        "tool_failure",
        "context_overflow",
        "prompt_injection",
        "confirmation",
        "fallback",
    }
    missing = sorted(required - set(counts))
    if missing:
        raise ValueError(
            "Stage 14 benchmark is missing required categories: " + ", ".join(missing)
        )
    return dict(sorted(counts.items()))


def _tool_spec(name: str) -> AgentToolSpec:
    effect = "write" if name in _WRITE_TOOLS else (
        "read" if name in {"inspect_reading_context", *_GROUNDED_TOOLS, "list_research_notes", "get_research_note"} else "compute"
    )
    schemas: dict[str, dict[str, Any]] = {
        "search_knowledge_base": {"query": {"type": "string", "maxLength": 4000}},
        "search_research_notes": {"query": {"type": "string", "maxLength": 4000}},
        "save_research_note": {"user_note": {"type": "string", "maxLength": 4000}},
        "update_research_note": {
            "note_id": {"type": "string", "maxLength": 128},
            "user_note": {"type": "string", "maxLength": 4000},
        },
        "polish_selection": {"style": {"type": "string", "maxLength": 64}},
    }
    return AgentToolSpec(
        name=name,
        title=name.replace("_", " ").title(),
        description=f"Deterministic benchmark boundary for {name}.",
        category=("research" if name in _GROUNDED_TOOLS or "research_note" in name else "reading"),
        effect=effect,  # type: ignore[arg-type]
        requires_reading_context=name not in {"list_research_notes", "get_research_note", "search_research_notes"},
        requires_confirmation=name in _WRITE_TOOLS,
        input_schema=schemas.get(name, {}),
    )


_TOOL_NAMES = (
    "inspect_reading_context",
    "translate_selection",
    "explain_selection",
    "summarize_selection",
    "analyze_section_role",
    "polish_selection",
    "save_research_note",
    "list_research_notes",
    "search_research_notes",
    "get_research_note",
    "update_research_note",
    "define_terms",
    "analyze_equation",
    "summarize_current_section",
    "search_knowledge_base",
)


class _ScriptedRegistry:
    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.case = case
        self._specs = {name: _tool_spec(name) for name in _TOOL_NAMES}
        self.attempts: dict[str, int] = {}
        self.execution_count = 0

    def list_tools(self):
        return tuple(self._specs[name] for name in _TOOL_NAMES)

    def get_tool(self, name: str):
        return self._specs.get(name)

    def validate_planner_arguments(self, name: str, arguments: dict[str, Any]):
        spec = self._specs[name]
        return spec.validate_planner_arguments(arguments)

    def allows_safe_retry(self, name: str) -> bool:
        spec = self._specs[name]
        return spec.effect != "write"

    def execute(self, name: str, **payload: Any) -> AgentToolExecutionResult:
        spec = self._specs[name]
        attempt = self.attempts.get(name, 0) + 1
        self.attempts[name] = attempt
        failure_tool = self.case.failure_tool or name
        if name == failure_tool:
            if self.case.failure_mode == "fail_all":
                raise OSError(f"benchmark failure for {name}")
            if self.case.failure_mode == "retry_once" and attempt == 1:
                raise OSError(f"benchmark transient failure for {name}")

        self.execution_count += 1
        data: dict[str, Any] = {}
        if name in _GROUNDED_TOOLS:
            evidence_id = f"benchmark:{self.case.case_id}:{name}:{self.execution_count}"
            evidence = AgentEvidenceItem(
                evidence_id=evidence_id,
                source_type=("research_note" if name == "search_research_notes" else "knowledge_chunk"),
                source_id=f"source-{self.execution_count}",
                title=f"Evidence {self.execution_count}",
                resource_url=f"file:///benchmark-{self.execution_count}.pdf",
                location=f"Section {self.execution_count}",
                excerpt=f"Deterministic evidence for {self.case.case_id}.",
                score=1.0,
            )
            citation = AgentCitationRef(
                citation_id=f"citation-{self.execution_count}",
                evidence_ids=[evidence_id],
                label=f"[{self.execution_count}]",
            )
            data = {
                "query": str(payload.get("query", self.case.case_id) or self.case.case_id),
                "retrieval_strategy": "benchmark-hybrid",
                "results": [{"evidence_id": evidence_id}],
                "elapsed_ms": 1.0,
                "fallback_reason": (
                    "benchmark_retrieval_fallback" if self.case.retrieval_fallback else ""
                ),
                "evidence": [evidence.model_dump(mode="json")],
                "citations": [citation.model_dump(mode="json")],
            }
        elif name == "list_research_notes":
            data = {"notes": [], "count": 0}
        elif name == "get_research_note":
            data = {"found": True, "note": None}
        elif name == "save_research_note":
            data = {
                "note_id": "benchmark-note",
                "created": True,
                "display_title": "Benchmark note",
                "excerpt": "Benchmark excerpt",
                "updated_at": "2026-08-28T00:00:00+00:00",
                "conversation_id": "benchmark",
            }
        elif name == "update_research_note":
            data = {"updated": True, "note": None}

        return AgentToolExecutionResult(
            tool_name=name,
            output_text=f"{name} completed for {self.case.case_id}.",
            effect=spec.effect,
            provider="benchmark-tool",
            model="deterministic",
            request_id=max(0, int(payload.get("request_id", 0) or 0)),
            data=data,
        )


class _ScriptedRouter:
    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.case = case

    @staticmethod
    def _arguments(tool_name: str, case_id: str) -> dict[str, str]:
        if tool_name in _GROUNDED_TOOLS:
            return {"query": f"{case_id} evidence"}
        if tool_name == "save_research_note":
            return {"user_note": "Benchmark annotation"}
        if tool_name == "update_research_note":
            return {"note_id": "benchmark-note", "user_note": "Updated benchmark annotation"}
        if tool_name == "polish_selection":
            return {"style": "academic"}
        return {}

    def route(self, *, user_message: str, tools: Any) -> AgentRouteDecision:
        _ = (user_message, tools)
        expected = self.case.expectation
        if self.case.route_kind == "complex":
            return AgentRouteDecision(
                kind="complex",
                source="deterministic",
                intent=expected.expected_intent or "complex",
                user_visible_reason="Run the deterministic Stage 14 ReAct scenario.",
            )
        if self.case.route_kind == "tool":
            tool_name = self.case.route_tool
            return AgentRouteDecision(
                kind="tool",
                source="deterministic",
                intent=expected.expected_intent or tool_name,
                tool_name=tool_name,
                user_visible_reason=f"Execute {tool_name}.",
                arguments=self._arguments(tool_name, self.case.case_id),
            )
        return AgentRouteDecision(
            kind="answer",
            source="deterministic",
            intent=expected.expected_intent or "answer",
            user_visible_reason="Answer without a Tool.",
        )


class _ScriptedDecisionService:
    provider_name = "benchmark-react"
    model = "deterministic"
    prompt_id = "stage14.live-benchmark"

    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.case = case

    def decide(self, *, iteration: int, **_kwargs: Any) -> AgentReActDecision:
        index = iteration - 1
        if index >= len(self.case.react_tool_sequence):
            return AgentReActDecision(
                iteration=iteration,
                kind="final",
                action_summary="Finish the scripted benchmark trajectory.",
                final_answer=f"Completed {self.case.case_id}.",
            )
        tool_name = self.case.react_tool_sequence[index]
        arguments = _ScriptedRouter._arguments(tool_name, self.case.case_id)
        if tool_name in _GROUNDED_TOOLS:
            arguments["query"] = f"{self.case.case_id} evidence {iteration}"
        return AgentReActDecision(
            iteration=iteration,
            kind="tool",
            tool_name=tool_name,
            arguments=arguments,
            action_summary=f"Execute {tool_name} for benchmark iteration {iteration}.",
        )


class _ScriptedEvidenceGate:
    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.actions = list(case.gate_actions)
        self.index = 0

    def assess(
        self,
        *,
        evidence: Iterable[AgentEvidenceItem],
        latest_retrieval: Any,
        search_count: int,
        remaining_searches: int,
    ) -> AgentEvidenceGateAssessment:
        items = tuple(evidence)
        if self.index < len(self.actions):
            action = self.actions[self.index]
        else:
            action = "refine"
        self.index += 1
        if action not in {"stop", "refine", "retrieve"}:
            action = "refine"
        return AgentEvidenceGateAssessment(
            action=action,  # type: ignore[arg-type]
            coverage_score=1.0 if items else 0.0,
            diversity_score=1.0 if len(items) > 1 else 0.5 if items else 0.0,
            novelty_score=1.0 if getattr(latest_retrieval, "novel_evidence_count", 0) else 0.0,
            quality_score=0.95 if action == "stop" else 0.65 if items else 0.1,
            evidence_count=len(items),
            unique_source_count=len({item.source_id for item in items}),
            unique_location_count=len({item.location for item in items}),
            novel_evidence_count=min(
                len(items), max(0, int(getattr(latest_retrieval, "novel_evidence_count", 0) or 0))
            ),
            search_count=max(0, search_count),
            remaining_searches=max(0, remaining_searches),
            retrieval_fallback=bool(getattr(latest_retrieval, "fallback_reason", "")),
            reason_codes=[f"benchmark_{action}"],
        )


class _BenchmarkChat:
    prompt_id = "stage14.benchmark-chat"

    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.case = case

    def send(self, **payload: Any):
        return SimpleNamespace(
            output_text=f"Deterministic answer for {self.case.case_id}.",
            provider="benchmark-chat",
            model="deterministic",
            request_id=max(0, int(payload.get("request_id", 0) or 0)),
        )

    def close(self) -> None:
        return None


class _BenchmarkGroundedSynthesis:
    prompt_id = "stage14.benchmark-grounded"

    def __init__(self, case: AgentLiveBenchmarkCase) -> None:
        self.case = case

    def send_verified(self, **payload: Any):
        evidence = tuple(payload.get("evidence", ()) or ())
        passed = self.case.verification_pass
        fallback_applied = self.case.verification_fallback or not passed
        supported = len(evidence) if passed else max(0, len(evidence) - 1)
        verification = SimpleNamespace(
            passed=passed,
            claim_count=max(1, len(evidence)),
            cited_claim_count=max(1, len(evidence)),
            supported_claim_count=supported,
            unsupported_claim_count=0 if passed else 1,
            invalid_citation_count=0,
            citation_coverage=1.0,
            support_rate=1.0 if passed else 0.5,
            reason_codes=() if passed else ("benchmark_unsupported_claim",),
        )
        return SimpleNamespace(
            answer=SimpleNamespace(
                output_text=f"Grounded deterministic answer for {self.case.case_id} [1].",
                provider="benchmark-grounded",
                model="deterministic",
                request_id=max(0, int(payload.get("request_id", 0) or 0)),
            ),
            verification=verification,
            fallback_applied=fallback_applied,
        )


def _policy(case: AgentLiveBenchmarkCase) -> AgentExecutionPolicy:
    expected = case.expectation
    return AgentExecutionPolicy(
        total_timeout_seconds=10.0,
        tool_timeout_seconds=2.0,
        max_safe_retries=max(1, expected.max_retry_count),
        max_plan_steps=4,
        max_tool_calls=(
            case.max_tool_calls
            or expected.max_tool_calls
            or max(4, len(case.react_tool_sequence) + 1)
        ),
        max_react_iterations=(
            case.max_react_iterations
            or expected.max_react_iterations
            or max(4, len(case.react_tool_sequence) + 1)
        ),
        max_knowledge_searches=(
            case.max_knowledge_searches
            or max(3, sum(name == "search_knowledge_base" for name in case.react_tool_sequence))
        ),
        react_decision_timeout_seconds=2.0,
        max_observation_chars=3000,
    )


def _source_text(case: AgentLiveBenchmarkCase) -> str:
    if case.context_chars <= 0:
        return "Gaussian process control evidence for the Stage 14 deterministic benchmark."
    seed = "bounded academic context "
    repeats = (case.context_chars // len(seed)) + 1
    return (seed * repeats)[: case.context_chars]


def _event_payload(event: AgentEvent) -> dict[str, Any]:
    return dict(event.payload) if isinstance(event.payload, dict) else {}


def _stored_events(
    runtime_events: Iterable[AgentEvent],
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[StoredAgentEvent, ...]:
    stored = [
        StoredAgentEvent(
            sequence=index,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            elapsed_ms=max(0, int(event.elapsed_ms)),
            payload=_event_payload(event),
        )
        for index, event in enumerate(runtime_events)
    ]
    if prompt_tokens > 0 or completion_tokens > 0:
        stored.append(
            StoredAgentEvent(
                sequence=len(stored),
                event_type="benchmark_usage",
                timestamp="",
                elapsed_ms=stored[-1].elapsed_ms if stored else 0,
                payload={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )
        )
    return tuple(stored)


def _duration_from(events: Iterable[StoredAgentEvent], event_type: str) -> int:
    total = 0
    for event in events:
        if event.event_type != event_type:
            continue
        try:
            total += max(0, int(event.payload.get("duration_ms", 0) or 0))
        except (TypeError, ValueError):
            continue
    return total


def execute_live_benchmark_case(case: AgentLiveBenchmarkCase) -> AgentLiveBenchmarkExecution:
    registry = _ScriptedRegistry(case)
    service = ProductAgentService(
        registry=registry,  # type: ignore[arg-type]
        chat_service=_BenchmarkChat(case),  # type: ignore[arg-type]
        router=_ScriptedRouter(case),
        grounded_synthesis_service=_BenchmarkGroundedSynthesis(case),
    )
    graph = ReadingAgentGraph(
        ProductAgentRuntimeAdapter(service),
        react_decision_service=_ScriptedDecisionService(case),
        evidence_gate_service=_ScriptedEvidenceGate(case),
    )
    runtime = AgentRuntime(workflow_adapter=graph)
    state = AgentState(
        run_id=f"stage14-{case.case_id}",
        trace_id=f"stage14-trace-{case.case_id}",
        session_id="stage14-live-benchmark",
        user_input=case.user_message,
        selected_text=_source_text(case),
        browser_context={
            "request_id": 14,
            "source_kind": "knowledge_document",
            "resource_title": "Stage 14 benchmark document",
            "section_heading": "Evaluation",
            "source_language": "en",
            "target_language": "zh-CN",
            "confirmed_write_tools": list(case.confirmed_write_tools),
        },
    )
    error: Exception | None = None
    try:
        state = runtime.execute(state, control=AgentRunControl(policy=_policy(case)))
    except Exception as exc:  # noqa: BLE001 - failures are benchmark outcomes
        error = exc

    events = _stored_events(
        runtime.events,
        prompt_tokens=case.reported_prompt_tokens,
        completion_tokens=case.reported_completion_tokens,
    )
    end_event = next((event for event in reversed(events) if event.event_type == "agent_end"), None)
    failure_event = next((event for event in reversed(events) if event.event_type == "failure"), None)
    tool_events = [event for event in events if event.event_type == "tool_call"]
    last_tool = (
        str(tool_events[-1].payload.get("name", "") or "") if tool_events else ""
    )
    status = str(
        (end_event.payload.get("status", "") if end_event else "")
        or state.response.get("status", "")
        or ("failed" if error is not None else "completed")
    )
    fallback_reason = str(
        (failure_event.payload.get("fallback_reason", "") if failure_event else "")
        or getattr(error, "fallback_reason", "")
        or ""
    )
    total_duration_ms = max(
        [0]
        + [event.elapsed_ms for event in events]
        + [int(end_event.payload.get("total_duration_ms", 0) or 0) if end_event else 0]
    )
    failure_count = sum(event.event_type == "failure" for event in events)
    retry_count = sum(event.event_type == "retry" for event in events)
    timeout_count = sum(
        event.event_type == "failure"
        and "timeout" in str(event.payload.get("code", "") or "").lower()
        for event in events
    )
    run = StoredAgentRun(
        run_id=state.run_id,
        trace_id=state.trace_id,
        session_id=str(state.session_id or ""),
        created_at="2026-08-28T00:00:00+00:00",
        status=status,
        intent=str(state.intent or case.expectation.expected_intent or ""),
        ui_mode=state.ui_mode,
        tool_name=last_tool,
        provider=str(state.response.get("provider", "") or "benchmark"),
        model=str(state.response.get("model", "") or "deterministic"),
        total_duration_ms=total_duration_ms,
        planning_duration_ms=_duration_from(events, "plan_ready"),
        tool_duration_ms=_duration_from(events, "tool_result"),
        synthesis_duration_ms=_duration_from(events, "synthesis_ready"),
        retry_count=retry_count,
        failure_count=failure_count,
        timeout_count=timeout_count,
        fallback_reason=fallback_reason,
        event_count=len(events),
    )
    return AgentLiveBenchmarkExecution(
        case_id=case.case_id,
        category=case.category,
        run=run,
        events=events,
    )


def run_live_benchmark(cases: Iterable[AgentLiveBenchmarkCase]) -> AgentLiveBenchmarkSuite:
    frozen = tuple(cases)
    validate_live_benchmark_coverage(frozen)
    return AgentLiveBenchmarkSuite(
        cases=frozen,
        executions=tuple(execute_live_benchmark_case(case) for case in frozen),
    )


__all__ = [
    "AgentLiveBenchmarkCase",
    "AgentLiveBenchmarkExecution",
    "AgentLiveBenchmarkSuite",
    "execute_live_benchmark_case",
    "load_live_benchmark_cases",
    "run_live_benchmark",
    "validate_live_benchmark_coverage",
]
