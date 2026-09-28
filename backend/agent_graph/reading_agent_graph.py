from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_config
from langgraph.runtime import Runtime
from langgraph.types import Command, Overwrite, Send

from app.ai.knowledge_context import knowledge_context_diagnostics
from backend.agent_core.events import AgentEventType
from backend.agent_core.exceptions import AgentRuntimeError
from backend.agent_core.orchestration.graph_state import (
    RootOrchestrationState,
    checkpoint_engine,
    checkpoint_graph_version,
    checkpoint_state_schema_version,
    import_legacy_orchestration_state,
    initial_orchestration_state,
    project_orchestration_state,
)
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.reliability import (
    AgentRunControl,
    run_node_operation_with_timeout,
    run_react_decision_with_timeout,
)
from backend.agent_core.state import (
    CURRENT_AGENT_GRAPH_VERSION,
    CURRENT_AGENT_STATE_SCHEMA_VERSION,
    LEGACY_AGENT_GRAPH_VERSION,
    PREVIOUS_AGENT_GRAPH_VERSION,
    PREVIOUS_NATIVE_AGENT_GRAPH_VERSION,
    SUPPORTED_AGENT_GRAPH_VERSIONS,
    AgentState,
    migrate_agent_state_payload,
)
from backend.agent_graph.factory import build_root_graph
from backend.models.agent_react import (
    AgentEvidenceGateAssessment,
    AgentObservation,
    AgentReActDecision,
    AgentRetrievalObservation,
    EvidenceSufficiency,
)
from backend.models.agent_runtime import (
    AgentEvidenceItem,
    AgentPlanStep,
    AgentRouteDecision,
)
from backend.services.agent_evidence_gate_service import AgentEvidenceGateService
from backend.services.agent_react_decision_service import AgentReActDecisionService

GraphEventSink = Callable[[AgentEventType, dict[str, Any]], None]
_KNOWLEDGE_SEARCH_TOOL = "search_knowledge_base"
_KNOWLEDGE_READ_TOOLS = frozenset(
    {"read_knowledge_chunk", "read_knowledge_section"}
)
from backend.agent_core.orchestration.agent_registry import AgentRegistry
from backend.agent_core.orchestration.frontier import (
    dependency_results,
    ready_tasks,
)
from backend.agent_core.orchestration.migration import resolve_agent_graph_engine
from backend.agent_core.orchestration.parallel_executor import ParallelExecutionPolicy
from backend.agent_core.orchestration.resource_manager import AgentResourceManager
from backend.agent_core.orchestration.specialist_adapter import (
    create_specialist_node,
    resolve_compiled_graph,
    resolve_per_invocation_graph,
    specialist_node_name,
)
from backend.models.agent_orchestration import OrchestrationLane, OrchestrationRoute
from backend.models.agent_tasks import (
    TERMINAL_TASK_STATUSES,
    ScopeContext,
    TaskResult,
    TaskStatus,
    ValidatedTaskPlan,
)


class ReadingAgentGraphState(RootOrchestrationState, total=False):
    """Serializable public state for production and LangSmith Studio."""

    agent_state: dict[str, Any]
    conversation_run: dict[str, Any]
    route: dict[str, Any]
    route_metadata: dict[str, Any]
    emitted_event_types: list[str]
    proposed_task_plan: dict[str, Any]


class ReadingAgentRuntimeContext(TypedDict, total=False):
    """Per-invocation objects that must never become Studio/checkpoint state."""

    event_sink: GraphEventSink | None
    control: AgentRunControl
    memory_snapshot: dict[str, Any]
    parallel_policy: Any
    resource_manager: AgentResourceManager
    resuming: bool
    durable_write_interrupt: bool
    write_confirmation_decision: dict[str, Any]


def _coerce_agent_state(value: AgentState | dict[str, Any]) -> AgentState:
    if isinstance(value, AgentState):
        return value
    return AgentState.model_validate(migrate_agent_state_payload(value))


def _dump_agent_state(state: AgentState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _dump_conversation_run(run: Any) -> dict[str, Any]:
    if run is None:
        return {}
    history = getattr(run, "history", ()) or ()
    return {
        "conversation_id": str(getattr(run, "conversation_id", "") or ""),
        "user_message_id": str(getattr(run, "user_message_id", "") or ""),
        "assistant_message_id": str(getattr(run, "assistant_message_id", "") or ""),
        "history": [
            [str(item[0]), str(item[1])]
            for item in history
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ],
        "owner_id": str(getattr(run, "owner_id", "") or ""),
        "request_id": max(0, int(getattr(run, "request_id", 0) or 0)),
    }


def _load_conversation_run(payload: dict[str, Any] | None) -> Any:
    if not payload:
        return None
    history = tuple(
        (str(item[0]), str(item[1]))
        for item in payload.get("history", ())
        if isinstance(item, (list, tuple)) and len(item) >= 2
    )
    return SimpleNamespace(
        conversation_id=str(payload.get("conversation_id", "") or ""),
        user_message_id=str(payload.get("user_message_id", "") or ""),
        assistant_message_id=str(payload.get("assistant_message_id", "") or ""),
        history=history,
        owner_id=str(payload.get("owner_id", "") or ""),
        request_id=max(0, int(payload.get("request_id", 0) or 0)),
    )


def _merge_emitted(existing: object, new_items: set[AgentEventType]) -> list[str]:
    values: set[str] = set()
    if isinstance(existing, (list, tuple, set, frozenset)):
        values.update(str(item) for item in existing if str(item))
    values.update(item.value for item in new_items)
    return sorted(values)


def _run_local_fingerprint(state: AgentState, payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    material = f"{state.run_id}\0{canonical}".encode()
    return hashlib.sha256(material).hexdigest()[:20]


def _react_action_fingerprint(state: AgentState, decision: AgentReActDecision) -> str:
    """Create a run-local opaque fingerprint for duplicate-action detection."""

    if decision.kind != "tool":
        return ""
    return _run_local_fingerprint(
        state,
        {
            "tool_name": decision.tool_name,
            "arguments": decision.arguments,
        },
    )


def _is_repeated_react_action(
    state: AgentState,
    decision: AgentReActDecision,
) -> bool:
    if decision.kind != "tool":
        return False
    return any(
        previous.kind == "tool"
        and previous.tool_name == decision.tool_name
        and previous.arguments == decision.arguments
        for previous in state.react.decisions[:-1]
    )


def _knowledge_search_count(state: AgentState) -> int:
    recorded = sum(
        str(item.get("name", "") or item.get("tool_name", "") or "")
        == _KNOWLEDGE_SEARCH_TOOL
        for item in state.tool_calls
        if isinstance(item, dict)
    )
    return max(
        int(state.knowledge_search_count),
        int(state.retrieval_attempt_count),
        recorded,
    )


def _knowledge_read_count(state: AgentState) -> int:
    recorded = sum(
        str(item.get("name", "") or item.get("tool_name", "") or "")
        in _KNOWLEDGE_READ_TOOLS
        for item in state.tool_calls
        if isinstance(item, dict)
    )
    return max(int(state.knowledge_read_count), recorded)


def _prior_evidence_ids(state: AgentState) -> set[str]:
    return {
        evidence_id
        for observation in state.react.observations
        for evidence_id in observation.evidence_ids
        if evidence_id
    }


def _cumulative_knowledge_evidence(state: AgentState) -> list[AgentEvidenceItem]:
    evidence: list[AgentEvidenceItem] = []
    seen: set[str] = set()
    for result in state.tool_results:
        if not isinstance(result, dict):
            continue
        tool_name = str(result.get("tool_name", "") or result.get("name", "") or "")
        if tool_name not in _KNOWLEDGE_READ_TOOLS:
            continue
        data = result.get("data", {})
        if not isinstance(data, dict):
            continue
        raw_evidence = data.get("evidence", ())
        if not isinstance(raw_evidence, (list, tuple)):
            continue
        for raw in raw_evidence:
            try:
                item = (
                    raw
                    if isinstance(raw, AgentEvidenceItem)
                    else AgentEvidenceItem.model_validate(raw)
                )
            except Exception:  # noqa: BLE001,S112 - discard malformed legacy evidence
                continue
            if item.evidence_id and item.evidence_id not in seen:
                evidence.append(item)
                seen.add(item.evidence_id)
    return evidence


def _latest_evidence_gate(state: AgentState) -> AgentEvidenceGateAssessment | None:
    for observation in reversed(state.react.observations):
        if observation.retrieval is not None and observation.retrieval.gate is not None:
            return observation.retrieval.gate
    return None


def _retrieval_observation(
    state: AgentState,
    decision: AgentReActDecision,
    result: dict[str, Any],
) -> AgentRetrievalObservation | None:
    if decision.tool_name != _KNOWLEDGE_SEARCH_TOOL and decision.tool_name not in _KNOWLEDGE_READ_TOOLS:
        return None
    data = dict(result.get("data", {}) or {})
    evidence_ids = [item.evidence_id for item in state.evidence]
    previous = _prior_evidence_ids(state)
    if decision.tool_name == _KNOWLEDGE_SEARCH_TOOL:
        results = data.get("results", ())
        result_count = len(results) if isinstance(results, (list, tuple)) else 0
    else:
        chunks = data.get("chunks", ())
        result_count = len(chunks) if isinstance(chunks, (list, tuple)) else 0
        data["retrieval_strategy"] = "jit_read"
        data["fallback_reason"] = ""
        if not data.get("query"):
            data["query"] = str(
                decision.arguments.get("chunk_id", "") or "section context read"
            )
    query = str(
        data.get("query", "")
        or decision.arguments.get("query", "")
        or decision.arguments.get("chunk_id", "")
        or ""
    ).strip()
    return AgentRetrievalObservation(
        query=query,
        retrieval_strategy=str(data.get("retrieval_strategy", "") or ""),
        result_count=result_count,
        evidence_count=len(evidence_ids),
        citation_count=len(state.citations),
        novel_evidence_count=sum(item not in previous for item in evidence_ids),
        fallback_reason=str(data.get("fallback_reason", "") or ""),
    )


class ReadingAgentGraph:
    """Bounded LangGraph workflow for the AITrans Reading Agent.

    Deterministic and single-tool requests stay on the established direct path.
    Only ``complex`` routes enter a bounded ReAct loop where the model chooses
    one registered Tool or Final per iteration and every Tool result is converted
    into a compact observation before the next decision. Knowledge retrieval is
    agentic only at the query/continue/stop layer; dense/sparse retrieval,
    fusion, reranking, evidence construction, and citations remain owned by the
    RAG subsystem. A deterministic evidence-sufficiency gate evaluates cumulative
    retrieval evidence and can stop further retrieval before another LLM decision
    is spent. Tool execution, safe retries, grounding, and write confirmation
    remain owned by the existing ProductAgentService boundary.
    """

    node_names = (
        "resolve_context",
        "run_collaboration",
        "prepare_conversation",
        "knowledge_access",
        "knowledge_scope",
        "route_request",
        "execute_direct",
        "start_react",
        "decide_react",
        "execute_react_tool",
        "finalize_react",
        "finalize_conversation",
    )
    native_node_names = (
        "route_orchestration",
        "resolve_scope",
        "load_memory_snapshot",
        "plan_tasks",
        "validate_plan",
        "block_orchestration",
    )

    def __init__(
        self,
        adapter: ProductAgentRuntimeAdapter,
        react_decision_service: AgentReActDecisionService | Any | None = None,
        evidence_gate_service: AgentEvidenceGateService | Any | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        context_provider: Callable[[AgentState], dict[str, Any]] | None = None,
        collaboration_adapter: Any | None = None,
        graph_version: str = CURRENT_AGENT_GRAPH_VERSION,
        state_schema_version: int = CURRENT_AGENT_STATE_SCHEMA_VERSION,
        engine: str | None = None,
        orchestration_service: Any | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self._adapter = adapter
        self._react_decision_service = (
            react_decision_service or AgentReActDecisionService()
        )
        self._evidence_gate_service = (
            evidence_gate_service or AgentEvidenceGateService()
        )
        self._checkpointer = checkpointer
        self._context_provider = context_provider
        self._collaboration_adapter = collaboration_adapter
        self._orchestration_service = orchestration_service or getattr(
            collaboration_adapter, "orchestrator", None
        )
        planner = getattr(self._orchestration_service, "planner", None)
        self._agent_registry = agent_registry or getattr(
            planner, "agent_registry", None
        )
        self._specialist_graph_cache: dict[str, Any] = {}
        self._specialist_checkpoint_graph_cache: dict[str, Any] = {}
        self._specialist_temporary_graph_cache: dict[str, Any] = {}
        self._specialist_node_names: dict[str, str] = {}
        self._send_dispatch_enabled = False
        self._graph_version = str(graph_version or "").strip()
        self._state_schema_version = int(state_schema_version)
        self._engine = str(
            engine if engine is not None else resolve_agent_graph_engine()
        ).strip().lower()
        if self._engine not in {"native", "compat"}:
            raise ValueError(f"unsupported Agent engine: {self._engine}")
        self._graph_version_pinned = False
        self._engine_pinned = False
        self._nodes: dict[str, Callable[..., Any]] = {
            "resolve_context": self._pausable_node(
                "resolve_context", self._resolve_context
            ),
            "run_collaboration": self._pausable_node(
                "run_collaboration", self._run_collaboration
            ),
            "prepare_conversation": self._pausable_node(
                "prepare_conversation", self._prepare_conversation, simple=True
            ),
            "route_orchestration": self._pausable_node(
                "route_orchestration", self._route_orchestration
            ),
            "resolve_scope": self._pausable_node("resolve_scope", self._resolve_scope),
            "load_memory_snapshot": self._pausable_node(
                "load_memory_snapshot", self._load_memory_snapshot
            ),
            "plan_tasks": self._pausable_node("plan_tasks", self._plan_tasks),
            "validate_plan": self._pausable_node("validate_plan", self._validate_plan),
            "dispatch_frontier": self._pausable_node(
                "dispatch_frontier", self._dispatch_frontier
            ),
            "advance_frontier": self._pausable_node(
                "advance_frontier", self._advance_frontier
            ),
            "finalize_task_graph": self._pausable_node(
                "finalize_task_graph", self._finalize_task_graph
            ),
            "block_orchestration": self._pausable_node(
                "block_orchestration", self._block_orchestration
            ),
            "knowledge_access": self._pausable_node(
                "knowledge_access", self._knowledge_access
            ),
            "knowledge_scope": self._pausable_node(
                "knowledge_scope", self._knowledge_scope
            ),
            "route_request": self._pausable_node(
                "route_request", self._route_request
            ),
            "execute_direct": self._pausable_node(
                "execute_direct", self._execute_direct
            ),
            "start_react": self._pausable_node("start_react", self._start_react),
            "decide_react": self._pausable_node(
                "decide_react", self._decide_react
            ),
            "execute_react_tool": self._pausable_node(
                "execute_react_tool", self._execute_react_tool
            ),
            "finalize_react": self._pausable_node(
                "finalize_react", self._finalize_react
            ),
            "finalize_conversation": self._pausable_node(
                "finalize_conversation", self._finalize_conversation, simple=True
            ),
        }
        self._compile_graphs()

    def _compile_graphs(self) -> None:
        nodes = {
            name: handler
            for name, handler in self._nodes.items()
            if not name.startswith("specialist_")
        }
        self._specialist_node_names = {}
        self._send_dispatch_enabled = False
        if self._uses_native_send_dispatch and self._agent_registry is not None:
            for spec in self._agent_registry.list_agents():
                if not callable(spec.graph_factory):
                    continue
                node_name = specialist_node_name(spec.agent_id)
                compiled = self._specialist_graph_cache.get(spec.agent_id)
                if compiled is None:
                    compiled = resolve_compiled_graph(
                        spec.agent_id, spec.graph_factory
                    )
                    self._specialist_graph_cache[spec.agent_id] = compiled
                checkpointed = self._specialist_checkpoint_graph_cache.get(
                    spec.agent_id
                )
                if checkpointed is None:
                    checkpointed = resolve_per_invocation_graph(
                        spec.agent_id, compiled
                    )
                    self._specialist_checkpoint_graph_cache[spec.agent_id] = (
                        checkpointed
                    )
                temporary_graph = None
                if callable(spec.temporary_graph_factory):
                    temporary_graph = self._specialist_temporary_graph_cache.get(
                        spec.agent_id
                    )
                    if temporary_graph is None:
                        temporary_graph = resolve_compiled_graph(
                            spec.agent_id, spec.temporary_graph_factory
                        )
                        self._specialist_temporary_graph_cache[spec.agent_id] = (
                            temporary_graph
                        )
                nodes[node_name] = create_specialist_node(
                    spec,
                    compiled,
                    checkpointed_graph=checkpointed,
                    temporary_graph=temporary_graph,
                )
                self._specialist_node_names[spec.agent_id] = node_name
            self._send_dispatch_enabled = bool(self._specialist_node_names)
        self._compiled, self._temporary_compiled = build_root_graph(
            state_schema=ReadingAgentGraphState,
            context_schema=ReadingAgentRuntimeContext,
            nodes=nodes,
            route_branch=self._route_branch,
            orchestration_branch=self._orchestration_branch,
            decision_branch=self._decision_branch,
            observation_branch=self._observation_branch,
            dispatch_branch=(
                self._dispatch_branch if self._send_dispatch_enabled else None
            ),
            checkpointer=self._checkpointer,
            graph_version=self._graph_version,
            engine=self._engine,
            native_send_dispatch=self._send_dispatch_enabled,
        )

    def select_graph_version(
        self,
        graph_version: str,
        *,
        state_schema_version: int | None = None,
        pin: bool = False,
        engine: str | None = None,
    ) -> None:
        """Select the checkpoint's builder before any state migration occurs."""

        selected = str(graph_version or "").strip()
        if selected not in SUPPORTED_AGENT_GRAPH_VERSIONS:
            raise AgentRuntimeError(
                f"unsupported Agent graph_version: {selected}",
                stage="checkpoint",
                fallback_reason="checkpoint_graph_version_unsupported",
            )
        schema_version = state_schema_version
        if schema_version is None:
            schema_version = {
                LEGACY_AGENT_GRAPH_VERSION: 1,
                "reading-agent-ma03-v1": 2,
                PREVIOUS_AGENT_GRAPH_VERSION: 3,
                PREVIOUS_NATIVE_AGENT_GRAPH_VERSION: 4,
                CURRENT_AGENT_GRAPH_VERSION: CURRENT_AGENT_STATE_SCHEMA_VERSION,
            }[selected]
        self._graph_version = selected
        self._state_schema_version = int(schema_version)
        self._graph_version_pinned = self._graph_version_pinned or pin
        if engine is not None:
            normalized_engine = str(engine or "").strip().lower()
            if normalized_engine not in {"native", "compat"}:
                raise AgentRuntimeError(
                    f"unsupported Agent engine: {normalized_engine}",
                    stage="checkpoint",
                    fallback_reason="checkpoint_engine_unsupported",
                )
            self._engine = normalized_engine
            self._engine_pinned = self._engine_pinned or pin
        self._compile_graphs()

    @property
    def compiled_graph(self):
        return self._compiled

    @property
    def manages_preworkflow(self) -> bool:
        return True

    def configure_preworkflow(
        self,
        *,
        context_provider: Callable[[AgentState], dict[str, Any]] | None = None,
        collaboration_adapter: Any | None = None,
    ) -> None:
        """Adopt legacy runtime adapters so existing compositions stay valid."""

        if context_provider is not None:
            self._context_provider = context_provider
        if collaboration_adapter is not None:
            self._collaboration_adapter = collaboration_adapter
            self._orchestration_service = getattr(
                collaboration_adapter,
                "orchestrator",
                self._orchestration_service,
            )

    @staticmethod
    def _checkpoint_config(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": str(run_id).strip()}}

    def _pausable_node(self, name: str, handler: Callable[..., dict[str, Any]], *, simple: bool = False):
        def guarded(
            graph_state: ReadingAgentGraphState,
            runtime: Runtime[ReadingAgentRuntimeContext],
        ) -> dict[str, Any]:
            _, control = self._runtime(runtime)
            control.pause_at_boundary(name)
            try:
                result = handler(graph_state) if simple else handler(graph_state, runtime)
            except Exception as exc:
                if name in {
                    "route_orchestration",
                    "resolve_scope",
                    "load_memory_snapshot",
                    "plan_tasks",
                    "validate_plan",
                    "dispatch_frontier",
                    "advance_frontier",
                    "finalize_task_graph",
                }:
                    self._abort(graph_state, exc)
                raise
            return {
                **result,
                "graph_version": self._graph_version,
                "state_schema_version": self._state_schema_version,
            }

        return guarded

    def _checkpoint_snapshot(self, run_id: str):
        normalized = str(run_id).strip()
        if self._checkpointer is None or not normalized:
            return None
        snapshot = self._compiled.get_state(self._checkpoint_config(normalized))
        if snapshot.values:
            try:
                raw_graph_version = checkpoint_graph_version(snapshot.values)
                raw_schema_version = checkpoint_state_schema_version(snapshot.values)
                raw_engine = checkpoint_engine(snapshot.values)
            except (TypeError, ValueError) as exc:
                reason = (
                    "checkpoint_schema_unsupported"
                    if "schema" in str(exc)
                    else "checkpoint_graph_version_unsupported"
                )
                raise AgentRuntimeError(
                    str(exc), stage="checkpoint", fallback_reason=reason
                ) from exc
            if (
                raw_graph_version != self._graph_version
                or raw_schema_version != self._state_schema_version
                or (
                    raw_graph_version == CURRENT_AGENT_GRAPH_VERSION
                    and raw_engine != self._engine
                )
            ):
                if self._graph_version_pinned or self._engine_pinned:
                    raise AgentRuntimeError(
                        "Persisted run version does not match checkpoint metadata.",
                        stage="checkpoint",
                        fallback_reason="checkpoint_graph_version_mismatch",
                    )
                self.select_graph_version(
                    raw_graph_version,
                    state_schema_version=raw_schema_version,
                    engine=(
                        raw_engine
                        if raw_graph_version == CURRENT_AGENT_GRAPH_VERSION
                        else self._engine
                    ),
                )
                snapshot = self._compiled.get_state(self._checkpoint_config(normalized))
        known_nodes = (
            set(self.node_names)
            | set(self.native_node_names)
            | set(self._specialist_node_names.values())
        )
        unknown_nodes = sorted(set(snapshot.next) - known_nodes)
        if unknown_nodes:
            raise AgentRuntimeError(
                f"Checkpoint references unsupported graph nodes: {unknown_nodes}",
                stage="checkpoint",
                fallback_reason="checkpoint_graph_version_unsupported",
            )
        payload = snapshot.values.get("agent_state") if snapshot.values else None
        if not isinstance(payload, dict):
            return None
        try:
            state = _coerce_agent_state(payload)
        except ValueError as exc:
            reason = (
                "checkpoint_schema_unsupported"
                if "schema" in str(exc)
                else "checkpoint_graph_version_unsupported"
            )
            raise AgentRuntimeError(
                str(exc), stage="checkpoint", fallback_reason=reason
            ) from exc
        if any(
            key in snapshot.values
            for key in ("scope", "task_plan", "task_results", "orchestration_status")
        ):
            projected = project_orchestration_state(
                snapshot.values,
                legacy=state.model_dump(mode="json"),
            )
            for field, value in projected.items():
                setattr(state, field, value)
        if state.run_id != normalized:
            raise AgentRuntimeError(
                f"Checkpoint run identity does not match {normalized!r}.",
                stage="checkpoint",
                fallback_reason="checkpoint_run_mismatch",
            )
        return snapshot, state

    def checkpoint_state(self, run_id: str) -> AgentState | None:
        """Load the latest durable state for one Agent run, if it exists."""

        resolved = self._checkpoint_snapshot(run_id)
        if resolved is None:
            return None
        snapshot, state = resolved
        pending_write = self._pending_checkpoint_write_tool(state, snapshot.next)
        if pending_write and not self._checkpoint_has_write_interrupt(
            snapshot, pending_write, state.run_id
        ):
            raise AgentRuntimeError(
                (
                    f"Checkpoint for run {run_id!r} is waiting to execute "
                    f"write tool {pending_write!r}; automatic replay is blocked."
                ),
                stage="checkpoint",
                fallback_reason="write_checkpoint_requires_manual_recovery",
            )
        return state

    @staticmethod
    def _checkpoint_has_write_interrupt(
        snapshot: Any, tool_name: str, run_id: str
    ) -> bool:
        """Allow resume only for a persisted, exact write-authorization interrupt."""

        for task in getattr(snapshot, "tasks", ()) or ():
            for item in getattr(task, "interrupts", ()) or ():
                value = getattr(item, "value", None)
                if not isinstance(value, dict):
                    continue
                if (
                    value.get("tool_name") == tool_name
                    and value.get("run_id") == run_id
                    and value.get("intent_id")
                    and value.get("arguments_hash")
                    and value.get("target_hash")
                    and value.get("step_id")
                ):
                    return True
        return False

    def _restore_memory_snapshot_context(
        self, state: AgentState, runtime_context: dict[str, Any]
    ) -> None:
        """Rehydrate frozen memory outside checkpoint channels before resume."""

        if self._orchestration_service is None:
            return
        snapshot_ref = str(state.memory_snapshot_ref or "").strip()
        scope_payload = state.orchestration_scope
        if not snapshot_ref or not isinstance(scope_payload, dict) or not scope_payload:
            return
        scope = ScopeContext.model_validate(scope_payload)
        request_context = self._orchestration_runtime_context(state)
        snapshot = self._orchestration_service.load_memory_snapshot(
            profile_id=str(request_context.get("profile_id", "local-default") or "local-default"),
            scope=scope,
            run_id=state.run_id,
            runtime_context=request_context,
        )
        if str(snapshot.get("snapshot_id", "") or "") != snapshot_ref:
            raise AgentRuntimeError(
                "The frozen memory snapshot no longer matches this checkpoint.",
                stage="memory",
                fallback_reason="memory_snapshot_invalidated",
            )
        runtime_context["memory_snapshot"] = snapshot

    def prepare_checkpoint_resume(self, run_id: str) -> None:
        """Read raw versions and select a compatible graph before migration."""

        self._checkpoint_snapshot(run_id)

    def checkpoint_orchestration_state(self, run_id: str) -> dict[str, Any] | None:
        resolved = self._checkpoint_snapshot(run_id)
        if resolved is None:
            return None
        snapshot, state = resolved
        values = snapshot.values or {}
        canonical_keys = (
            "graph_version",
            "engine",
            "state_schema_version",
            "orchestration_route",
            "scope",
            "plan_revision",
            "memory_policy_revision",
            "memory_snapshot_ref",
            "task_plan",
            "task_results",
            "task_status_by_id",
            "frontier_task_ids",
            "active_frontier_task_ids",
            "artifact_refs",
            "evidence_refs",
            "event_ids",
            "event_fingerprints",
            "orchestration_status",
        )
        if any(key in values for key in canonical_keys[2:]):
            return {key: values[key] for key in canonical_keys if key in values}
        return import_legacy_orchestration_state(state.model_dump(mode="json"))

    def checkpoint_metadata(self, run_id: str) -> dict[str, str | int] | None:
        resolved = self._checkpoint_snapshot(run_id)
        if resolved is None:
            return None
        snapshot, _state = resolved
        configurable = (snapshot.config or {}).get("configurable", {})
        return {
            "graph_version": checkpoint_graph_version(snapshot.values or {}),
            "engine": checkpoint_engine(snapshot.values or {}),
            "state_schema_version": checkpoint_state_schema_version(
                snapshot.values or {}
            ),
            "checkpoint_id": str(configurable.get("checkpoint_id", "") or ""),
        }

    def prepare_task_retry(self, state: AgentState, task_id: str) -> tuple[str, ...]:
        if self._uses_native_send_dispatch:
            return self._prepare_native_task_retry(state, task_id)
        adapter = self._collaboration_adapter
        prepare = getattr(adapter, "prepare_task_retry", None)
        if not callable(prepare):
            raise AgentRuntimeError(
                "Task retry is unavailable for this Agent workflow.",
                stage="checkpoint",
                fallback_reason="task_retry_unavailable",
            )
        return tuple(prepare(state, task_id))

    def _prepare_native_task_retry(
        self, state: AgentState, task_id: str
    ) -> tuple[str, ...]:
        if self._checkpointer is None or self._agent_registry is None:
            raise AgentRuntimeError(
                "Native task retry requires a durable Root checkpoint and Agent registry.",
                stage="checkpoint",
                fallback_reason="task_retry_unavailable",
            )
        resolved = self._checkpoint_snapshot(state.run_id)
        if resolved is None:
            raise AgentRuntimeError(
                "No Root checkpoint is available for this retry.",
                stage="checkpoint",
                fallback_reason="checkpoint_not_found",
            )
        snapshot, _checkpoint_state = resolved
        values = dict(snapshot.values or {})
        plan = ValidatedTaskPlan.model_validate(values.get("task_plan", {}))
        scope = ScopeContext.model_validate(values.get("scope", {}))
        target_id = str(task_id or "").strip()
        task_map = plan.task_map()
        if target_id not in task_map:
            raise ValueError(f"unknown retry task: {target_id}")
        target = task_map[target_id]
        results = [
            TaskResult.model_validate(item)
            for item in values.get("task_results", ())
        ]
        latest: dict[str, TaskResult] = {}
        for result in results:
            if result.task_id not in latest or (
                result.attempt_ordinal,
                result.result_version,
            ) > (
                latest[result.task_id].attempt_ordinal,
                latest[result.task_id].result_version,
            ):
                latest[result.task_id] = result
        current = latest.get(target_id)
        retryable_statuses = {
            TaskStatus.FAILED,
            TaskStatus.PARTIAL,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
            TaskStatus.BLOCKED,
        }
        if current is None or current.status not in retryable_statuses:
            raise ValueError("only a completed failed or partial task can be retried")

        affected = {target_id}
        changed = True
        while changed:
            changed = False
            for task in plan.tasks:
                if task.task_id not in affected and affected.intersection(task.depends_on):
                    affected.add(task.task_id)
                    changed = True
        successful_statuses = {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL}
        unresolved_dependencies = sorted(
            dependency
            for dependency in target.depends_on
            if dependency not in latest
            or latest[dependency].status not in successful_statuses
        )
        if unresolved_dependencies:
            raise ValueError(
                "task retry requires successful dependencies: "
                + ", ".join(unresolved_dependencies)
            )

        attempts: dict[str, int] = {
            str(key): max(1, int(value))
            for key, value in dict(values.get("task_attempt_ordinals", {})).items()
        }
        for result in results:
            attempts[result.task_id] = max(
                attempts.get(result.task_id, 1), result.attempt_ordinal
            )
        next_attempts: dict[str, int] = {}
        for retry_id in sorted(affected):
            retry_task = task_map[retry_id]
            spec = self._agent_registry.get(retry_task.agent_id)
            next_attempt = attempts.get(retry_id, 1) + 1
            if next_attempt > spec.retry_policy.max_retries + 1:
                raise ValueError(
                    f"task {retry_id} exhausted its retry policy"
                )
            next_attempts[retry_id] = next_attempt

        # Refresh scope/source authority, frozen Memory policy and plan contract
        # before mutating the checkpoint. Reuse the same validator as durable
        # Root resume, then verify retained ArtifactRefs before preserving them.
        service = self._orchestration_service
        revalidate = getattr(service, "revalidate_prepared", None)
        if not callable(revalidate):
            raise AgentRuntimeError(
                "Native task retry cannot revalidate scope and Memory policy.",
                stage="scope",
                fallback_reason="retry_revalidation_unavailable",
            )
        profile_id = str(
            self._orchestration_runtime_context(state).get("profile_id", "local-default")
            or "local-default"
        )
        fresh_scope, _fresh_memory = revalidate(
            profile_id=profile_id,
            scope=scope,
            task_plan=plan,
            run_id=state.run_id,
            runtime_context=self._orchestration_runtime_context(state),
        )
        if fresh_scope.scope_ref != scope.scope_ref:
            raise AgentRuntimeError(
                "The prepared scope changed before task retry.",
                stage="scope",
                fallback_reason="prepared_scope_changed",
            )

        remaining_results = [item for item in results if item.task_id not in affected]
        artifact_refs = [
            ref
            for result in remaining_results
            for ref in result.artifact_refs
        ]
        evidence_refs = [
            ref
            for result in remaining_results
            for ref in result.evidence_refs
        ]
        executor = getattr(service, "executor", None)
        artifact_store = getattr(executor, "_artifacts", None) or getattr(
            service, "artifact_store", None
        )
        for result in remaining_results:
            task = task_map[result.task_id]
            for ref in result.artifact_refs:
                artifact = (
                    artifact_store.get(ref.artifact_id, ref.version)
                    if artifact_store is not None
                    else None
                )
                if (
                    artifact is None
                    or artifact.content_hash != ref.content_hash
                    or artifact.scope_ref != fresh_scope.scope_ref
                    or artifact.producer_task_id != task.task_id
                    or artifact.kind is not ref.kind
                    or ref.kind is not task.expected_output_kind
                ):
                    raise AgentRuntimeError(
                        "A retained ArtifactRef failed retry revalidation.",
                        stage="artifact",
                        fallback_reason="retry_artifact_invalid",
                    )

        # The reducer channels use Overwrite so stale failed results and their
        # references cannot win the Root dispatch projection on replay.
        root_config = self._checkpoint_config(state.run_id)
        update: dict[str, Any] = {
            "task_results": Overwrite(
                [item.model_dump(mode="json") for item in remaining_results]
            ),
            "task_status_by_id": {
                **dict(values.get("task_status_by_id", {})),
                **{retry_id: TaskStatus.PENDING.value for retry_id in affected},
            },
            "task_attempt_ordinals": {
                **attempts,
                **next_attempts,
            },
            "retry_task_ids": sorted(affected),
            "active_frontier_task_ids": [],
            "frontier_task_ids": [],
            "artifact_refs": Overwrite(
                [ref.model_dump(mode="json") for ref in artifact_refs]
            ),
            "evidence_refs": Overwrite(
                [ref.model_dump(mode="json") for ref in evidence_refs]
            ),
            "orchestration_status": "retrying",
        }
        self._compiled.update_state(root_config, update, as_node="validate_plan")
        context = dict(state.browser_context)
        context["native_task_retry_resume"] = True
        context["retry_task_id"] = target_id
        state.browser_context = context
        state.orchestration_results = [
            item.model_dump(mode="json") for item in remaining_results
        ]
        state.orchestration_status = "retrying"
        state.sync_contract()
        return tuple(sorted(affected))

    def _pending_checkpoint_write_tool(
        self,
        state: AgentState,
        next_nodes: tuple[str, ...],
    ) -> str:
        if not {"execute_direct", "execute_react_tool"}.intersection(next_nodes):
            return ""

        tool_name = state.route.tool_name
        if "execute_react_tool" in next_nodes and state.react.decisions:
            tool_name = state.react.decisions[-1].tool_name
        if not tool_name:
            return ""
        for spec in self._registered_tools():
            if (
                str(getattr(spec, "name", "") or "") == tool_name
                and str(getattr(spec, "effect", "") or "") == "write"
            ):
                return tool_name
        return ""

    @staticmethod
    def _runtime(
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> tuple[GraphEventSink | None, AgentRunControl]:
        context = runtime.context or {}
        return context.get("event_sink"), context.get("control") or AgentRunControl()

    def _abort(self, graph_state: ReadingAgentGraphState, exc: Exception) -> None:
        self._adapter.abort_conversation(
            _load_conversation_run(graph_state.get("conversation_run")),
            exc,
        )

    def _registered_tools(self) -> tuple[Any, ...]:
        service = getattr(self._adapter, "_service", None)
        list_tools = getattr(service, "list_tools", None)
        if callable(list_tools):
            return tuple(list_tools())
        registry = getattr(service, "_registry", None)
        list_tools = getattr(registry, "list_tools", None)
        if callable(list_tools):
            return tuple(list_tools())
        return ()

    def _run_registered_tools(self, state: AgentState) -> tuple[Any, ...]:
        visible = getattr(self._adapter, "registered_tools", None)
        if callable(visible):
            return tuple(visible(state))
        return self._registered_tools()

    def _resolve_context(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        control.checkpoint("context_resolution")
        if self._context_provider is not None:
            state.apply_reading_context(self._context_provider(state))
        else:
            state.sync_contract()
        canonical = import_legacy_orchestration_state(
            _dump_agent_state(state), prior=graph_state
        )
        for field, value in project_orchestration_state(
            canonical, legacy=_dump_agent_state(state)
        ).items():
            setattr(state, field, value)
        control.checkpoint("context_ready")

        emitted: set[AgentEventType] = set()
        if emit is not None:
            public_context = {
                key: value
                for key, value in state.browser_context.items()
                if key != "knowledge_context"
            }
            emit(AgentEventType.CONTEXT_READY, public_context)
            emitted.add(AgentEventType.CONTEXT_READY)
            knowledge_diagnostics = knowledge_context_diagnostics(
                state.browser_context.get("knowledge_context")
            )
            if knowledge_diagnostics:
                emit(
                    AgentEventType.KNOWLEDGE_CONTEXT_READY,
                    knowledge_diagnostics,
                )
                emitted.add(AgentEventType.KNOWLEDGE_CONTEXT_READY)
        return {
            "agent_state": _dump_agent_state(state),
            **canonical,
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _run_collaboration(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        adapter = self._collaboration_adapter
        if adapter is None:
            return {"agent_state": _dump_agent_state(state)}

        emit, control = self._runtime(runtime)
        if self._uses_native_topology:
            route = OrchestrationRoute.model_validate(
                graph_state.get("orchestration_route", {})
            )
            scope = ScopeContext.model_validate(graph_state.get("scope", {}))
            raw_plan = graph_state.get("task_plan", {})
            task_plan = (
                ValidatedTaskPlan.model_validate(raw_plan) if raw_plan else None
            )
            prepared_runner = getattr(adapter, "run_prepared", None)
            if not callable(prepared_runner):
                raise AgentRuntimeError(
                    "Native Root execution requires a prepared-plan bridge.",
                    stage="orchestration",
                    fallback_reason="prepared_executor_unavailable",
                )
            try:
                state = prepared_runner(
                    state,
                    route=route,
                    scope=scope,
                    memory_snapshot=dict(
                        (runtime.context or {}).get("memory_snapshot", {}) or {}
                    ),
                    task_plan=task_plan,
                    precomputed_results=(
                        [
                            TaskResult.model_validate(item)
                            for item in graph_state.get("task_results", ())
                        ]
                        if self._send_dispatch_enabled
                        else None
                    ),
                    emit=lambda event_type, payload: (
                        emit(event_type, payload) if emit is not None else None
                    ),
                    control=control,
                    resuming=bool((runtime.context or {}).get("resuming", False)),
                )
            except Exception as exc:
                self._abort(graph_state, exc)
                raise
            state.sync_contract()
            canonical = import_legacy_orchestration_state(
                _dump_agent_state(state), prior=graph_state
            )
            for field, value in project_orchestration_state(
                canonical, legacy=_dump_agent_state(state)
            ).items():
                setattr(state, field, value)
            return {
                "agent_state": _dump_agent_state(state),
                **canonical,
                "orchestration_status": state.orchestration_status,
            }
        prepare_state = getattr(adapter, "prepare_state", None)
        if callable(prepare_state):
            state = prepare_state(state)
        should_run = getattr(adapter, "should_run", None)
        if callable(should_run) and not bool(should_run(state)):
            return {"agent_state": _dump_agent_state(state)}

        emitted: set[AgentEventType] = set()

        def forward(event_type: AgentEventType, payload: dict[str, Any]) -> None:
            emitted.add(event_type)
            if emit is not None:
                emit(event_type, payload)

        eventful_run = getattr(adapter, "run_with_events", None)
        if callable(eventful_run):
            state = eventful_run(state, forward, control=control)
        elif callable(adapter):
            state = adapter(state)
        state.sync_contract()
        canonical = import_legacy_orchestration_state(
            _dump_agent_state(state), prior=graph_state
        )
        for field, value in project_orchestration_state(
            canonical, legacy=_dump_agent_state(state)
        ).items():
            setattr(state, field, value)
        return {
            "agent_state": _dump_agent_state(state),
            **canonical,
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _emit_react_limit(
        self,
        state: AgentState,
        emit: GraphEventSink | None,
        *,
        reason: str,
    ) -> set[AgentEventType]:
        state.mark_react_status("limit_reached")
        if emit is None:
            return set()
        emit(
            AgentEventType.REACT_LIMIT_REACHED,
            {
                "iteration": state.react.iteration,
                "tool_call_count": len(state.tool_calls),
                "knowledge_search_count": _knowledge_search_count(state),
                "knowledge_read_count": _knowledge_read_count(state),
                "reason": reason,
            },
        )
        return {AgentEventType.REACT_LIMIT_REACHED}

    def _prepare_conversation(
        self, graph_state: ReadingAgentGraphState
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        conversation_run = self._adapter.begin_conversation(state)
        return {
            "agent_state": _dump_agent_state(state),
            "conversation_run": _dump_conversation_run(conversation_run),
        }

    def _knowledge_access(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        control.checkpoint("knowledge_access")
        decision = self._adapter.resolve_knowledge_access(state)
        emitted: set[AgentEventType] = set()
        if emit is not None:
            payload = decision.model_dump(mode="json")
            query = str(payload.pop("query", "") or "")
            payload["query_chars"] = len(query)
            emit(AgentEventType.KNOWLEDGE_DECISION, payload)
            emitted.add(AgentEventType.KNOWLEDGE_DECISION)
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    @property
    def _uses_native_topology(self) -> bool:
        return (
            self._graph_version
            in {PREVIOUS_NATIVE_AGENT_GRAPH_VERSION, CURRENT_AGENT_GRAPH_VERSION}
            and self._engine == "native"
        )

    @property
    def _uses_native_send_dispatch(self) -> bool:
        return (
            self._graph_version == CURRENT_AGENT_GRAPH_VERSION
            and self._engine == "native"
        )

    @staticmethod
    def _emit_root_event(
        runtime: Runtime[ReadingAgentRuntimeContext],
        event_type: AgentEventType,
        payload: dict[str, Any],
    ) -> None:
        context = runtime.context if isinstance(runtime.context, dict) else {}
        emit = context.get("event_sink")
        if callable(emit):
            emit(event_type, payload)

    def _resource_manager(
        self, runtime: Runtime[ReadingAgentRuntimeContext]
    ) -> AgentResourceManager:
        context = runtime.context if isinstance(runtime.context, dict) else {}
        manager = context.get("resource_manager")
        if isinstance(manager, AgentResourceManager):
            return manager
        policy = context.get("parallel_policy")
        if policy is None:
            executor = getattr(self._orchestration_service, "executor", None)
            policy = getattr(executor, "policy", None) or ParallelExecutionPolicy()
        manager = AgentResourceManager(policy)
        if isinstance(runtime.context, dict):
            runtime.context["resource_manager"] = manager
        return manager

    def _dispatch_frontier(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        raw_plan = graph_state.get("task_plan", {})
        if not raw_plan:
            raise AgentRuntimeError(
                "Native dispatch has no validated task plan.",
                stage="orchestration",
                fallback_reason="prepared_plan_missing",
            )
        plan = ValidatedTaskPlan.model_validate(raw_plan)
        results = [
            TaskResult.model_validate(item)
            for item in graph_state.get("task_results", ())
        ]
        statuses = {
            str(key): TaskStatus(value)
            for key, value in graph_state.get("task_status_by_id", {}).items()
        }
        attempt_ordinals = {
            str(key): max(1, int(value))
            for key, value in graph_state.get("task_attempt_ordinals", {}).items()
        }
        manager = self._resource_manager(runtime)
        new_results: list[dict[str, Any]] = []
        new_statuses: dict[str, str] = {}
        active_ids: list[str] = []
        task_map = plan.task_map()

        # Resolve failed dependency and exhausted-budget tasks locally before
        # returning Sends. Recompute until every newly terminal descendant has
        # propagated through the DAG.
        while True:
            ready_ids = ready_tasks(plan, results, statuses)
            if not ready_ids:
                break
            made_progress = False
            for task_id in ready_ids:
                task = task_map[task_id]
                projection = dependency_results(task, results)
                if projection.failed_task_ids:
                    result = projection.failure_result(task)
                    results.append(result)
                    new_results.append(result.model_dump(mode="json"))
                    statuses[task_id] = result.status
                    new_statuses[task_id] = result.status.value
                    event_type = (
                        AgentEventType.TASK_BLOCKED
                        if result.status is TaskStatus.BLOCKED
                        else AgentEventType.TASK_SKIPPED
                    )
                    self._emit_root_event(
                        runtime,
                        event_type,
                        {
                            "task_id": task_id,
                            "agent_id": task.agent_id,
                            "status": result.status.value,
                            "reason_code": result.error_code,
                        },
                    )
                    made_progress = True
                    continue
                if not manager.budget.reserve("model_calls", 1):
                    status = TaskStatus.BLOCKED if task.required else TaskStatus.SKIPPED
                    result = TaskResult(
                        task_id=task_id,
                        attempt_id=f"{task_id}:{attempt_ordinals.get(task_id, 1)}",
                        attempt_ordinal=attempt_ordinals.get(task_id, 1),
                        status=status,
                        error_code="budget_exhausted",
                    )
                    results.append(result)
                    new_results.append(result.model_dump(mode="json"))
                    statuses[task_id] = status
                    new_statuses[task_id] = status.value
                    self._emit_root_event(
                        runtime,
                        AgentEventType.BUDGET_EXHAUSTED,
                        {"task_id": task_id, "agent_id": task.agent_id},
                    )
                    self._emit_root_event(
                        runtime,
                        AgentEventType.TASK_BLOCKED
                        if status is TaskStatus.BLOCKED
                        else AgentEventType.TASK_SKIPPED,
                        {
                            "task_id": task_id,
                            "agent_id": task.agent_id,
                            "status": status.value,
                            "reason_code": "budget_exhausted",
                        },
                    )
                    made_progress = True
                    continue
                statuses[task_id] = TaskStatus.RUNNING
                new_statuses[task_id] = TaskStatus.RUNNING.value
                active_ids.append(task_id)
                self._emit_root_event(
                    runtime,
                    AgentEventType.TASK_READY,
                    {
                        "task_id": task_id,
                        "agent_id": task.agent_id,
                        "status": "ready",
                    },
                )
                made_progress = True
            if active_ids or not made_progress:
                break

        return {
            "task_results": new_results,
            "task_status_by_id": new_statuses,
            "active_frontier_task_ids": active_ids,
            "frontier_task_ids": active_ids,
            "orchestration_status": "running",
        }

    def _dispatch_branch(self, graph_state: ReadingAgentGraphState) -> Any:
        plan = ValidatedTaskPlan.model_validate(graph_state.get("task_plan", {}))
        active_ids = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in graph_state.get("active_frontier_task_ids", ())
                    if str(item).strip()
                }
            )
        )
        result_map = {
            item.task_id: item
            for item in (
                TaskResult.model_validate(raw)
                for raw in graph_state.get("task_results", ())
            )
        }
        attempt_ordinals = {
            str(key): max(1, int(value))
            for key, value in graph_state.get("task_attempt_ordinals", {}).items()
        }
        if not active_ids:
            if set(result_map) == set(plan.task_map()) and all(
                item.status in TERMINAL_TASK_STATUSES for item in result_map.values()
            ):
                return "finalize"
            raise AgentRuntimeError(
                "The validated task graph has no executable frontier.",
                stage="orchestration",
                fallback_reason="frontier_stalled",
            )
        scope = ScopeContext.model_validate(graph_state.get("scope", {}))
        task_map = plan.task_map()
        sends: list[Send] = []
        for task_id in active_ids:
            task = task_map.get(task_id)
            node_name = self._specialist_node_names.get(task.agent_id) if task else None
            if task is None or not node_name:
                raise AgentRuntimeError(
                    f"No registered specialist node for task {task_id}.",
                    stage="orchestration",
                    fallback_reason="specialist_graph_unavailable",
                )
            projected = dependency_results(task, result_map)
            if projected.failed_task_ids or projected.missing_task_ids:
                raise AgentRuntimeError(
                    f"Task {task_id} dependencies changed after frontier selection.",
                    stage="orchestration",
                    fallback_reason="frontier_dependency_conflict",
                )
            sends.append(
                Send(
                    node_name,
                    {
                        "task": task,
                        "scope": scope,
                        "dependency_results": dict(projected.results),
                        "attempt_ordinal": attempt_ordinals.get(task_id, 1),
                    },
                )
            )
        return sends

    def _advance_frontier(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        del runtime
        results = {
            item.task_id: item
            for item in (
                TaskResult.model_validate(raw)
                for raw in graph_state.get("task_results", ())
            )
        }
        active_ids = tuple(graph_state.get("active_frontier_task_ids", ()))
        missing = sorted(
            task_id
            for task_id in active_ids
            if task_id not in results
            or results[task_id].status not in TERMINAL_TASK_STATUSES
        )
        if missing:
            raise AgentRuntimeError(
                "The specialist frontier returned without terminal results: "
                + ", ".join(missing),
                stage="orchestration",
                fallback_reason="specialist_result_missing",
            )
        return {"active_frontier_task_ids": []}

    def _finalize_task_graph(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        del runtime
        plan = ValidatedTaskPlan.model_validate(graph_state.get("task_plan", {}))
        results = {
            item.task_id: item
            for item in (
                TaskResult.model_validate(raw)
                for raw in graph_state.get("task_results", ())
            )
        }
        missing = sorted(set(plan.task_map()) - set(results))
        if missing or any(
            result.status not in TERMINAL_TASK_STATUSES
            for result in results.values()
        ):
            raise AgentRuntimeError(
                "Cannot finalize a task graph with nonterminal results.",
                stage="orchestration",
                fallback_reason="task_graph_incomplete",
            )
        complete = all(
            item.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL, TaskStatus.SKIPPED}
            for item in results.values()
        )
        return {
            "active_frontier_task_ids": [],
            "orchestration_status": "completed" if complete else "partial",
        }

    def _orchestration_runtime_context(
        self, state: AgentState
    ) -> dict[str, Any]:
        adapter_context = getattr(self._collaboration_adapter, "_runtime_context", None)
        if callable(adapter_context):
            return dict(adapter_context(state))
        context = state.browser_context
        return {
            "profile_id": str(context.get("profile_id", "local-default") or "local-default"),
            "multi_agent_mode": str(context.get("multi_agent_mode", "auto") or "auto"),
            "source_text": state.selected_text,
            "workspace_id": str(context.get("workspace_id", "") or ""),
            "knowledge_board_id": str(context.get("knowledge_board_id", "") or ""),
            "knowledge_collection_id": str(context.get("knowledge_collection_id", "") or ""),
            "research_source_ids": list(context.get("research_source_ids", ()) or ()),
            "research_note_ids": list(context.get("research_note_ids", ()) or ()),
            "knowledge_document_ids": list(context.get("knowledge_document_ids", ()) or ()),
            "knowledge_item_ids": list(context.get("knowledge_item_ids", ()) or ()),
            "temporary": bool(context.get("temporary", False)),
            "workflow_action": str(context.get("workflow_action", "") or ""),
        }

    def _route_orchestration(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        service = self._orchestration_service
        _, control = self._runtime(runtime)
        if service is None or self._collaboration_adapter is None:
            route = OrchestrationRoute(
                lane=OrchestrationLane.FAST,
                reason_code="orchestration_unavailable",
                user_visible_reason="The canonical Agent path is sufficient.",
            )
        else:
            context = self._orchestration_runtime_context(state)
            mode = str(context.get("multi_agent_mode", "auto") or "auto")
            route = run_node_operation_with_timeout(
                lambda: service.route(state.user_input, context, mode=mode),
                control=control,
                node_timeout_seconds=control.policy.node_timeout_seconds,
                stage="route_orchestration",
            )
            maximum_lane = getattr(
                self._collaboration_adapter, "maximum_lane", OrchestrationLane.WORKFLOW
            )
            if (
                maximum_lane is OrchestrationLane.SINGLE
                and route.lane is OrchestrationLane.WORKFLOW
            ):
                route = OrchestrationRoute(
                    lane=OrchestrationLane.FAST,
                    reason_code="rollout_lane_limit",
                    user_visible_reason="The current rollout uses the canonical Agent path.",
                )
        return {"orchestration_route": route.model_dump(mode="json")}

    @staticmethod
    def _orchestration_branch(graph_state: ReadingAgentGraphState) -> str:
        route = OrchestrationRoute.model_validate(
            graph_state.get("orchestration_route", {})
        )
        if route.missing_information:
            return "blocked"
        return "fast" if route.lane is OrchestrationLane.FAST else "plan"

    def _resolve_scope(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        del runtime
        if self._orchestration_service is None:
            raise AgentRuntimeError(
                "Native orchestration has no scope resolver.",
                stage="scope",
                fallback_reason="scope_resolver_unavailable",
            )
        state = _coerce_agent_state(graph_state["agent_state"])
        context = self._orchestration_runtime_context(state)
        scope = self._orchestration_service.resolve_scope(
            profile_id=str(context.get("profile_id", "local-default") or "local-default"),
            runtime_context=context,
        )
        return {
            "scope": scope.model_dump(mode="json"),
            "memory_policy_revision": scope.memory_policy_revision,
        }

    def _load_memory_snapshot(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        if self._orchestration_service is None:
            raise AgentRuntimeError(
                "Native orchestration has no memory boundary.",
                stage="memory",
                fallback_reason="memory_port_unavailable",
            )
        state = _coerce_agent_state(graph_state["agent_state"])
        context = self._orchestration_runtime_context(state)
        scope = ScopeContext.model_validate(graph_state.get("scope", {}))
        snapshot = self._orchestration_service.load_memory_snapshot(
            profile_id=str(context.get("profile_id", "local-default") or "local-default"),
            scope=scope,
            run_id=state.run_id,
            runtime_context=context,
        )
        invocation_context = runtime.context
        if isinstance(invocation_context, dict):
            # Snapshot bodies stay in invocation context; checkpoints retain only IDs.
            invocation_context["memory_snapshot"] = snapshot
        return {"memory_snapshot_ref": str(snapshot.get("snapshot_id", "") or "")}

    def _plan_tasks(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        if self._orchestration_service is None:
            raise AgentRuntimeError(
                "Native orchestration has no planner.",
                stage="planning",
                fallback_reason="planner_unavailable",
            )
        state = _coerce_agent_state(graph_state["agent_state"])
        route = OrchestrationRoute.model_validate(
            graph_state.get("orchestration_route", {})
        )
        scope = ScopeContext.model_validate(graph_state.get("scope", {}))
        plan_revision = max(1, int(graph_state.get("plan_revision", 0) or 1))
        _, control = self._runtime(runtime)
        plan = run_node_operation_with_timeout(
            lambda: self._orchestration_service.plan_tasks(
                route=route,
                objective=state.user_input,
                scope=scope,
                plan_revision=plan_revision,
            ),
            control=control,
            node_timeout_seconds=control.policy.node_timeout_seconds,
            stage="plan_tasks",
        )
        if plan is None and not route.missing_information:
            raise AgentRuntimeError(
                "The Root planner did not produce a plan for a specialist route.",
                stage="planning",
                fallback_reason="prepared_plan_missing",
            )
        return {
            "proposed_task_plan": (
                plan.model_dump(mode="json") if plan is not None else {}
            )
        }

    def _validate_plan(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        if self._orchestration_service is None:
            raise AgentRuntimeError(
                "Native orchestration has no plan validator.",
                stage="planning",
                fallback_reason="plan_validator_unavailable",
            )
        scope = ScopeContext.model_validate(graph_state.get("scope", {}))
        proposed = graph_state.get("proposed_task_plan", {})
        plan = ValidatedTaskPlan.model_validate(proposed) if proposed else None
        validated = self._orchestration_service.validate_plan(
            plan,
            scope=scope,
            require_graphs=self._send_dispatch_enabled,
        )
        if validated is None:
            raise AgentRuntimeError(
                "The prepared specialist plan is empty.",
                stage="planning",
                fallback_reason="prepared_plan_missing",
            )
        statuses = {task.task_id: "pending" for task in validated.tasks}
        self._emit_root_event(
            runtime,
            AgentEventType.MULTI_AGENT_STARTED,
            {"lane": "workflow", "scope_ref": scope.scope_ref},
        )
        self._emit_root_event(
            runtime,
            AgentEventType.MULTI_AGENT_PLAN_READY,
            {
                "plan_revision": validated.plan_revision,
                "task_count": len(validated.tasks),
                "agents": [task.agent_id for task in validated.tasks],
            },
        )
        for task in validated.tasks:
            self._emit_root_event(
                runtime,
                AgentEventType.TASK_PLANNED,
                {
                    "task_id": task.task_id,
                    "agent_id": task.agent_id,
                    "role": task.agent_id,
                    "depends_on": list(task.depends_on),
                    "required": task.required,
                    "output_kind": task.expected_output_kind.value,
                    "attempt": 0,
                    "plan_revision": task.plan_revision,
                    "status": "pending",
                },
            )
        checkpoint_delta = {
            "task_plan": validated.model_dump(mode="json"),
            "plan_revision": validated.plan_revision,
            "task_status_by_id": statuses,
            "orchestration_status": "planned",
            "proposed_task_plan": {},
        }
        if self._checkpointer is not None and self._uses_native_topology:
            config = get_config()
            thread_id = str(
                config.get("configurable", {}).get("thread_id", "") or ""
            )
            if thread_id:
                # LangGraph persists the completed step at the superstep boundary.
                # Write the validated plan now as well, before the executor can
                # perform any specialist side effects.
                root_config: dict[str, Any] = {
                    "configurable": {"thread_id": thread_id, "checkpoint_ns": ""}
                }
                parent_id = str(config.get("checkpoint_map", {}).get("", "") or "")
                if parent_id:
                    root_config["configurable"]["checkpoint_id"] = parent_id
                self._compiled.update_state(
                    root_config, checkpoint_delta, as_node="validate_plan"
                )
        return checkpoint_delta

    def _block_orchestration(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        route = OrchestrationRoute.model_validate(
            graph_state.get("orchestration_route", {})
        )
        details = ", ".join(route.missing_information)
        message = (
            "This research action needs additional scoped input before it can run: "
            + details
        )
        state.apply_response(
            {
                "status": "completed",
                "output_text": message,
                "provider": "orchestration-router",
                "model": "",
                "request_id": state.execution.request_id,
            }
        )
        state.apply_orchestration(
            lane=route.lane.value,
            status="blocked",
            scope=dict(graph_state.get("scope", {}) or {}),
            plan=None,
            results=[],
            memory_snapshot_ref=str(graph_state.get("memory_snapshot_ref", "") or ""),
        )
        emit, _ = self._runtime(runtime)
        if emit is not None:
            emit(
                AgentEventType.MULTI_AGENT_COMPLETED,
                {
                    "actor": "supervisor",
                    "status": "blocked",
                    "reason_code": "missing_information",
                    "missing_information": list(route.missing_information),
                },
            )
        return {"agent_state": _dump_agent_state(state), "orchestration_status": "blocked"}

    def _knowledge_scope(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        control.checkpoint("knowledge_scope")
        decision = self._adapter.resolve_knowledge_access(state)
        scope = self._adapter.resolve_knowledge_scope(state, decision=decision)
        emitted: set[AgentEventType] = set()
        if emit is not None:
            emit(
                AgentEventType.KNOWLEDGE_SCOPE_RESOLVED,
                {
                    "strategy": scope.strategy.value,
                    "document_count": len(scope.document_ids),
                    "research_source_count": len(scope.research_source_ids),
                    "workspace_selected": bool(scope.workspace_id),
                    "allow_global": scope.allow_global,
                    "reason": scope.reason[:256],
                },
            )
            emitted.add(AgentEventType.KNOWLEDGE_SCOPE_RESOLVED)
            if not decision.should_retrieve:
                emit(
                    AgentEventType.KNOWLEDGE_SKIPPED,
                    {
                        "reason_code": decision.reason_code,
                        "scope_strategy": decision.scope_strategy.value,
                        "query_chars": len(decision.query),
                    },
                )
                emitted.add(AgentEventType.KNOWLEDGE_SKIPPED)
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _route_request(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        _, control = self._runtime(runtime)
        if (
            state.browser_context.get("orchestration_direct_delivery")
            and state.response_state.status == "completed"
        ):
            route = AgentRouteDecision(
                kind="answer",
                source="deterministic",
                intent="orchestration_direct_delivery",
                user_visible_reason="A completed bounded task result already satisfies the request.",
            )
            state.apply_route(route)
            return {
                "agent_state": _dump_agent_state(state),
                "route": route.model_dump(mode="json"),
                "route_metadata": {"direct_delivery": True},
            }
        try:
            working_state = state.model_copy(deep=True)

            def resolve_route() -> tuple[AgentRouteDecision, dict[str, Any], AgentState]:
                route_value, metadata_value = self._adapter.resolve_route(
                    working_state, control=control
                )
                return route_value, metadata_value, working_state

            route, metadata, state = run_node_operation_with_timeout(
                resolve_route,
                control=control,
                node_timeout_seconds=control.policy.node_timeout_seconds,
                stage="route_request",
            )
        except Exception as exc:
            self._abort(graph_state, exc)
            raise
        return {
            "agent_state": _dump_agent_state(state),
            "route": route.model_dump(mode="json"),
            "route_metadata": dict(metadata),
        }

    @staticmethod
    def _route_branch(graph_state: ReadingAgentGraphState) -> str:
        state = _coerce_agent_state(graph_state["agent_state"])
        if (
            state.browser_context.get("orchestration_direct_delivery")
            and state.response_state.status == "completed"
        ):
            return "completed"
        route = AgentRouteDecision.model_validate(graph_state.get("route", {}))
        return "complex" if route.kind == "complex" else "direct"

    def _execute_direct(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        route = AgentRouteDecision.model_validate(graph_state.get("route", {}))
        emit, control = self._runtime(runtime)
        try:
            state, emitted = self._adapter.execute_product(
                state,
                emit,
                control=control,
                resolved_route=route,
                route_metadata=dict(graph_state.get("route_metadata", {}) or {}),
                durable_write_interrupt=bool(
                    (runtime.context or {}).get("durable_write_interrupt", False)
                ),
            )
        except Exception as exc:
            self._abort(graph_state, exc)
            raise
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _start_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        state.start_react()
        emitted: set[AgentEventType] = set()
        if emit is not None:
            route_metadata = dict(graph_state.get("route_metadata", {}) or {})
            emit(
                AgentEventType.PLAN_READY,
                {
                    "mode": "react",
                    "route_kind": state.route.kind,
                    "route_source": state.route.source,
                    "request_id": state.execution.request_id,
                    **route_metadata,
                },
            )
            emit(
                AgentEventType.REACT_STARTED,
                {
                    "max_iterations": control.policy.max_react_iterations,
                    "max_tool_calls": control.policy.max_tool_calls,
                    "max_knowledge_searches": control.policy.max_knowledge_searches,
                    "max_knowledge_reads": control.policy.max_knowledge_reads,
                    "request_id": state.execution.request_id,
                },
            )
            emitted.update({AgentEventType.PLAN_READY, AgentEventType.REACT_STARTED})
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _decide_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        if state.react.iteration >= control.policy.max_react_iterations:
            emitted = self._emit_react_limit(
                state, emit, reason="iteration_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        latest_gate = _latest_evidence_gate(state)
        if latest_gate is not None and latest_gate.action == "stop":
            decision = AgentReActDecision(
                iteration=state.react.iteration + 1,
                kind="final",
                action_summary="Use the accumulated evidence after the retrieval quality gate stopped further search.",
            )
            state.record_react_decision(decision)
            emitted: set[AgentEventType] = set()
            if emit is not None:
                emit(
                    AgentEventType.DECISION_READY,
                    {
                        "iteration": decision.iteration,
                        "kind": decision.kind,
                        "tool_name": "",
                        "argument_keys": [],
                        "action_fingerprint": "",
                        "provider": "deterministic-evidence-gate",
                        "model": "",
                        "prompt_id": "evidence-gate",
                    },
                )
                emitted.add(AgentEventType.DECISION_READY)
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        tools = self._run_registered_tools(state)
        if not tools:
            exc = AgentRuntimeError(
                "Complex ReAct route has no registered tools.",
                stage="react_decision",
                fallback_reason="missing_tool_registry",
            )
            self._abort(graph_state, exc)
            raise exc

        iteration = state.react.iteration + 1
        knowledge_search_count = _knowledge_search_count(state)
        knowledge_read_count = _knowledge_read_count(state)
        payload = self._adapter.build_payload(state)
        try:
            decision = run_react_decision_with_timeout(
                lambda: self._react_decision_service.decide(
                    iteration=iteration,
                    tools=tools,
                    observations=tuple(state.react.observations),
                    max_observation_chars=control.policy.max_observation_chars,
                    remaining_tool_calls=max(
                        0, control.policy.max_tool_calls - len(state.tool_calls)
                    ),
                    remaining_knowledge_searches=max(
                        0,
                        min(
                            control.policy.max_knowledge_searches,
                            control.policy.max_tool_calls,
                        )
                        - knowledge_search_count,
                    ),
                    remaining_knowledge_reads=max(
                        0,
                        min(
                            control.policy.max_knowledge_reads,
                            control.policy.max_tool_calls,
                        )
                        - knowledge_read_count,
                    ),
                    **payload,
                ),
                control=control,
            )
            state.record_react_decision(decision)
        except Exception as exc:
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        emitted: set[AgentEventType] = set()
        action_fingerprint = _react_action_fingerprint(state, decision)
        if emit is not None:
            emit(
                AgentEventType.DECISION_READY,
                {
                    "iteration": decision.iteration,
                    "kind": decision.kind,
                    "tool_name": decision.tool_name,
                    "argument_keys": sorted(decision.arguments),
                    "action_fingerprint": action_fingerprint,
                    "action_summary": decision.action_summary,
                    "provider": str(
                        getattr(self._react_decision_service, "provider_name", "") or ""
                    ),
                    "model": str(
                        getattr(self._react_decision_service, "model", "") or ""
                    ),
                    "prompt_id": str(
                        getattr(self._react_decision_service, "prompt_id", "") or ""
                    ),
                },
            )
            emitted.add(AgentEventType.DECISION_READY)

        if _is_repeated_react_action(state, decision):
            emitted.update(
                self._emit_react_limit(state, emit, reason="repeated_action_detected")
            )
        elif (
            decision.kind == "tool"
            and decision.tool_name == _KNOWLEDGE_SEARCH_TOOL
            and knowledge_search_count
            >= min(control.policy.max_knowledge_searches, control.policy.max_tool_calls)
        ):
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="knowledge_search_budget_exhausted"
                )
            )
        elif (
            decision.kind == "tool"
            and decision.tool_name in _KNOWLEDGE_READ_TOOLS
            and knowledge_read_count
            >= min(control.policy.max_knowledge_reads, control.policy.max_tool_calls)
        ):
            emitted.update(
                self._emit_react_limit(
                    state, emit, reason="knowledge_read_budget_exhausted"
                )
            )

        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    @staticmethod
    def _decision_branch(graph_state: ReadingAgentGraphState) -> str:
        state = _coerce_agent_state(graph_state["agent_state"])
        if state.react.status == "limit_reached":
            return "limit"
        decision = state.react.last_decision
        if decision is None:
            raise AgentRuntimeError(
                "ReAct decision node completed without a decision.",
                stage="react_decision",
                fallback_reason="missing_react_decision",
            )
        return "tool" if decision.kind == "tool" else "final"

    def _execute_react_tool(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        decision = state.react.last_decision
        if decision is None or decision.kind != "tool":
            exc = AgentRuntimeError(
                "ReAct action node requires a tool decision.",
                stage="react_action",
                fallback_reason="invalid_react_action",
            )
            self._abort(graph_state, exc)
            raise exc

        if len(state.tool_calls) >= control.policy.max_tool_calls:
            emitted = self._emit_react_limit(
                state, emit, reason="tool_call_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }
        if decision.tool_name == _KNOWLEDGE_SEARCH_TOOL and _knowledge_search_count(
            state
        ) >= min(control.policy.max_knowledge_searches, control.policy.max_tool_calls):
            emitted = self._emit_react_limit(
                state, emit, reason="knowledge_search_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }
        if decision.tool_name in _KNOWLEDGE_READ_TOOLS and _knowledge_read_count(
            state
        ) >= min(control.policy.max_knowledge_reads, control.policy.max_tool_calls):
            emitted = self._emit_react_limit(
                state, emit, reason="knowledge_read_budget_exhausted"
            )
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        step = AgentPlanStep(
            step_id=f"react-{decision.iteration}",
            tool_name=decision.tool_name,
            arguments=dict(decision.arguments),
        )
        try:
            state, emitted = self._adapter.execute_plan_step(
                state,
                step,
                emit,
                control=control,
                durable_write_interrupt=bool(
                    (runtime.context or {}).get("durable_write_interrupt", False)
                ),
            )
        except Exception as exc:
            if decision.tool_name == _KNOWLEDGE_SEARCH_TOOL:
                state.evidence_sufficient = False
                state.evidence_sufficiency = EvidenceSufficiency(
                    sufficient=False,
                    reason="retrieval_failed",
                    missing_information=["retrievable evidence"],
                )
                observation = AgentObservation(
                    iteration=decision.iteration,
                    tool_name=decision.tool_name,
                    success=False,
                    summary="Knowledge retrieval failed; no new evidence was added.",
                    error_code="retrieval_failed",
                    evidence_ids=[item.evidence_id for item in state.evidence],
                    citation_ids=[item.citation_id for item in state.citations],
                )
                state.record_react_observation(observation)
                emitted: set[AgentEventType] = set()
                if emit is not None:
                    emit(
                        AgentEventType.OBSERVATION_READY,
                        {
                            "observation_id": observation.observation_id,
                            "iteration": observation.iteration,
                            "tool_name": observation.tool_name,
                            "success": False,
                            "summary_chars": len(observation.summary),
                            "error_code": observation.error_code,
                            "evidence_count": len(observation.evidence_ids),
                            "citation_count": len(observation.citation_ids),
                        },
                    )
                    emitted.add(AgentEventType.OBSERVATION_READY)
                    emit(
                        AgentEventType.EVIDENCE_SUFFICIENCY,
                        {
                            "sufficient": False,
                            "reason": "retrieval_failed",
                            "missing_information": ["retrievable evidence"],
                            "search_count": _knowledge_search_count(state),
                            "knowledge_search_count": _knowledge_search_count(state),
                            "knowledge_read_count": _knowledge_read_count(state),
                        },
                    )
                    emitted.add(AgentEventType.EVIDENCE_SUFFICIENCY)
                if state.react.iteration >= control.policy.max_react_iterations:
                    emitted.update(
                        self._emit_react_limit(
                            state, emit, reason="iteration_budget_exhausted"
                        )
                    )
                elif _knowledge_search_count(state) >= min(
                    control.policy.max_knowledge_searches,
                    control.policy.max_tool_calls,
                ):
                    emitted.update(
                        self._emit_react_limit(
                            state, emit, reason="knowledge_search_budget_exhausted"
                        )
                    )
                elif _knowledge_read_count(state) >= min(
                    control.policy.max_knowledge_reads,
                    control.policy.max_tool_calls,
                ):
                    emitted.update(
                        self._emit_react_limit(
                            state, emit, reason="knowledge_read_budget_exhausted"
                        )
                    )
                return {
                    "agent_state": _dump_agent_state(state),
                    "emitted_event_types": _merge_emitted(
                        graph_state.get("emitted_event_types", ()), emitted
                    ),
                }
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        if state.response_state.status == "confirmation_required":
            state.mark_react_status("confirmation_required")
            return {
                "agent_state": _dump_agent_state(state),
                "emitted_event_types": _merge_emitted(
                    graph_state.get("emitted_event_types", ()), emitted
                ),
            }

        result = state.tool_results[-1] if state.tool_results else {}
        summary = str(result.get("output_text", "") or "").strip()
        if not summary:
            summary = f"{decision.tool_name} completed."
        summary = summary[: control.policy.max_observation_chars]
        retrieval = _retrieval_observation(state, decision, result)

        if retrieval is not None:
            search_count = _knowledge_search_count(state)
            max_searches = min(
                control.policy.max_knowledge_searches,
                control.policy.max_tool_calls,
            )
            gate = self._evidence_gate_service.assess(
                evidence=_cumulative_knowledge_evidence(state),
                latest_retrieval=retrieval,
                search_count=search_count,
                remaining_searches=max(0, max_searches - search_count),
            )
            if (
                decision.tool_name == _KNOWLEDGE_SEARCH_TOOL
                and retrieval.result_count > 0
                and gate.action == "stop"
                and "evidence_sufficient" not in gate.reason_codes
            ):
                gate = gate.model_copy(
                    update={
                        "action": "refine",
                        "reason_codes": [
                            *gate.reason_codes,
                            "located_candidates_available",
                        ],
                    }
                )
            state.evidence_sufficient = bool(
                gate.action == "stop" and "evidence_sufficient" in gate.reason_codes
            )
            state.evidence_sufficiency = EvidenceSufficiency(
                sufficient=bool(state.evidence_sufficient),
                reason=(
                    "evidence_sufficient"
                    if state.evidence_sufficient
                    else (gate.reason_codes[0] if gate.reason_codes else "evidence_insufficient")
                ),
                missing_information=[
                    reason
                    for reason in gate.reason_codes
                    if reason.startswith("insufficient_")
                ],
            )
            retrieval = retrieval.model_copy(update={"gate": gate})
            if emit is not None:
                emit(
                    AgentEventType.EVIDENCE_GATE_EVALUATED,
                    {
                        "iteration": decision.iteration,
                        "action": gate.action,
                        "coverage_score": gate.coverage_score,
                        "diversity_score": gate.diversity_score,
                        "novelty_score": gate.novelty_score,
                        "quality_score": gate.quality_score,
                        "evidence_count": gate.evidence_count,
                        "unique_source_count": gate.unique_source_count,
                        "unique_location_count": gate.unique_location_count,
                        "novel_evidence_count": gate.novel_evidence_count,
                        "search_count": gate.search_count,
                        "knowledge_search_count": _knowledge_search_count(state),
                        "knowledge_read_count": _knowledge_read_count(state),
                        "remaining_searches": gate.remaining_searches,
                        "retrieval_fallback": gate.retrieval_fallback,
                        "reason_codes": list(gate.reason_codes),
                    },
                )
                emitted.add(AgentEventType.EVIDENCE_GATE_EVALUATED)
                emit(
                    AgentEventType.EVIDENCE_SUFFICIENCY,
                    {
                        "sufficient": state.evidence_sufficiency.sufficient,
                        "reason": state.evidence_sufficiency.reason,
                        "missing_information": list(
                            state.evidence_sufficiency.missing_information
                        ),
                        "search_count": gate.search_count,
                        "knowledge_search_count": _knowledge_search_count(state),
                        "knowledge_read_count": _knowledge_read_count(state),
                    },
                )
                emitted.add(AgentEventType.EVIDENCE_SUFFICIENCY)

        observation = AgentObservation(
            iteration=decision.iteration,
            tool_name=decision.tool_name,
            success=True,
            summary=summary,
            evidence_ids=[item.evidence_id for item in state.evidence],
            citation_ids=[item.citation_id for item in state.citations],
            retrieval=retrieval,
        )
        state.record_react_observation(observation)

        if emit is not None:
            observation_payload: dict[str, Any] = {
                "observation_id": observation.observation_id,
                "iteration": observation.iteration,
                "tool_name": observation.tool_name,
                "success": observation.success,
                "summary_chars": len(observation.summary),
                "evidence_count": len(observation.evidence_ids),
                "citation_count": len(observation.citation_ids),
            }
            if retrieval is not None:
                observation_payload.update(
                    {
                        "knowledge_search_count": _knowledge_search_count(state),
                        "knowledge_read_count": _knowledge_read_count(state),
                        "query_fingerprint": _run_local_fingerprint(
                            state, {"query": retrieval.query}
                        ),
                        "retrieval_strategy": retrieval.retrieval_strategy,
                        "result_count": retrieval.result_count,
                        "novel_evidence_count": retrieval.novel_evidence_count,
                        "retrieval_fallback": bool(retrieval.fallback_reason),
                        "gate_action": (
                            retrieval.gate.action if retrieval.gate is not None else ""
                        ),
                        "gate_quality_score": (
                            retrieval.gate.quality_score
                            if retrieval.gate is not None
                            else 0.0
                        ),
                    }
                )
            emit(AgentEventType.OBSERVATION_READY, observation_payload)
            emitted.add(AgentEventType.OBSERVATION_READY)

        latest_gate = _latest_evidence_gate(state)
        evidence_stop = bool(
            latest_gate is not None
            and latest_gate.action == "stop"
            and "evidence_sufficient" in latest_gate.reason_codes
        )
        if len(state.tool_calls) >= control.policy.max_tool_calls and not evidence_stop:
            emitted.update(
                self._emit_react_limit(state, emit, reason="tool_call_budget_exhausted")
            )
        elif state.react.iteration >= control.policy.max_react_iterations:
            emitted.update(
                self._emit_react_limit(state, emit, reason="iteration_budget_exhausted")
            )

        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    @staticmethod
    def _observation_branch(graph_state: ReadingAgentGraphState) -> str:
        state = _coerce_agent_state(graph_state["agent_state"])
        if state.response_state.status == "confirmation_required":
            return "confirmation"
        if state.react.status == "limit_reached":
            return "finalize"
        if state.react.observations:
            latest = state.react.observations[-1]
            if (
                latest.tool_name == _KNOWLEDGE_SEARCH_TOOL
                and latest.retrieval is not None
                and latest.retrieval.result_count > 0
            ):
                return "continue"
        gate = _latest_evidence_gate(state)
        if gate is not None and gate.action == "stop":
            return "finalize"
        return "continue"

    def _finalize_react(
        self,
        graph_state: ReadingAgentGraphState,
        runtime: Runtime[ReadingAgentRuntimeContext],
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        emit, control = self._runtime(runtime)
        emitted: set[AgentEventType] = set()

        try:
            if state.tool_results:
                state, emitted = self._adapter.synthesize_multi_step(
                    state,
                    emit,
                    control=control,
                )
            else:
                decision: AgentReActDecision | None = state.react.last_decision
                if (
                    decision is None
                    or decision.kind != "final"
                    or not decision.final_answer
                ):
                    if state.evidence_sufficient is False:
                        state.ui_mode = "assistant"
                        state.apply_response(
                            {
                                "status": "completed",
                                "output_text": (
                                    "Knowledge retrieval did not produce sufficient "
                                    "evidence to answer reliably."
                                ),
                                "provider": "deterministic-fallback",
                                "model": "",
                                "request_id": state.execution.request_id,
                            }
                        )
                        if emit is not None:
                            emit(
                                AgentEventType.SYNTHESIS_READY,
                                {
                                    "source": "retrieval_fallback",
                                    "provider": "deterministic-fallback",
                                    "model": "",
                                    "request_id": state.execution.request_id,
                                    "prompt_id": "evidence-insufficient",
                                    "grounded": False,
                                    "evidence_sufficient": False,
                                },
                            )
                            emitted.add(AgentEventType.SYNTHESIS_READY)
                    else:
                        raise AgentRuntimeError(
                            "ReAct reached its execution limit before producing an answer or observation.",
                            stage="react_finalize",
                            fallback_reason="react_limit_without_observation",
                        )
                else:
                    state.ui_mode = "assistant"
                    state.apply_response(
                        {
                            "status": "completed",
                            "output_text": decision.final_answer,
                            "provider": str(
                                getattr(self._react_decision_service, "provider_name", "")
                                or ""
                            ),
                            "model": str(
                                getattr(self._react_decision_service, "model", "") or ""
                            ),
                            "request_id": state.execution.request_id,
                        }
                    )
                    if emit is not None:
                        emit(
                            AgentEventType.SYNTHESIS_READY,
                            {
                                "source": "react_decision",
                                "provider": state.response_state.provider,
                                "model": state.response_state.model,
                                "request_id": state.execution.request_id,
                                "prompt_id": str(
                                    getattr(self._react_decision_service, "prompt_id", "")
                                    or ""
                                ),
                                "grounded": False,
                            },
                        )
                        emitted.add(AgentEventType.SYNTHESIS_READY)
        except Exception as exc:
            state.mark_react_status("failed")
            self._abort(graph_state, exc)
            raise

        if state.react.status != "limit_reached":
            state.mark_react_status("completed")
        return {
            "agent_state": _dump_agent_state(state),
            "emitted_event_types": _merge_emitted(
                graph_state.get("emitted_event_types", ()), emitted
            ),
        }

    def _finalize_conversation(
        self,
        graph_state: ReadingAgentGraphState,
    ) -> dict[str, Any]:
        state = _coerce_agent_state(graph_state["agent_state"])
        self._adapter.complete_conversation(
            _load_conversation_run(graph_state.get("conversation_run")), state
        )
        return {"agent_state": _dump_agent_state(state)}

    def _invoke(
        self,
        state: AgentState,
        *,
        emit: GraphEventSink | None,
        control: AgentRunControl | None,
        resume: bool = False,
    ) -> tuple[AgentState, set[AgentEventType]]:
        initial: ReadingAgentGraphState = {
            "agent_state": _dump_agent_state(state),
            "conversation_run": {},
            "route": {},
            "route_metadata": {},
            "emitted_event_types": [],
        }
        initial.update(
            initial_orchestration_state(
                scope=state.orchestration_scope,
                task_plan=state.orchestration_plan,
                task_results=state.orchestration_results,
                orchestration_status=state.orchestration_status,
                memory_snapshot_ref=state.memory_snapshot_ref,
                graph_version=self._graph_version,
                state_schema_version=self._state_schema_version,
                engine=self._engine,
            )
        )
        temporary = bool(state.browser_context.get("temporary", False))
        if resume and temporary:
            raise AgentRuntimeError(
                "Temporary Agent runs cannot be resumed across process boundaries.",
                stage="checkpoint",
                fallback_reason="temporary_checkpoint_unavailable",
            )
        if resume and self._checkpointer is None:
            raise AgentRuntimeError(
                "Agent checkpoint persistence is unavailable.",
                stage="checkpoint",
                fallback_reason="checkpoint_unavailable",
            )
        graph = self._temporary_compiled if temporary else self._compiled
        runtime_context: dict[str, Any] = {
            "event_sink": emit,
            "control": control or AgentRunControl(),
            "resuming": bool(resume),
            "temporary": temporary,
            "persistent_checkpoints": self._checkpointer is not None and not temporary,
            "durable_write_interrupt": bool(
                self._uses_native_topology
                and self._checkpointer is not None
                and not temporary
            ),
            "write_confirmation_decision": dict(
                state.browser_context.get("write_confirmation_decision", {}) or {}
            ),
        }
        if self._send_dispatch_enabled:
            executor = getattr(self._orchestration_service, "executor", None)
            policy = getattr(executor, "policy", None) or ParallelExecutionPolicy()
            runtime_context.update(
                {
                    "parallel_policy": policy,
                    "resource_manager": AgentResourceManager(policy),
                    "memory_snapshot": {},
                }
            )
            if resume and not temporary:
                self._restore_memory_snapshot_context(state, runtime_context)
        resume_decision = runtime_context.get("write_confirmation_decision")
        graph_input = (
            Command(resume=resume_decision)
            if resume and resume_decision
            else None
            if resume
            else initial
        )
        result = graph.invoke(
            graph_input,
            config=(
                self._checkpoint_config(state.run_id)
                if self._checkpointer is not None and not temporary
                else None
            ),
            context=runtime_context,
            durability=(
                "sync"
                if self._checkpointer is not None and not temporary
                else None
            ),
        )
        final_state = _coerce_agent_state(
            result.get("agent_state", initial["agent_state"])
        )
        interrupts = result.get("__interrupt__", ())
        if interrupts:
            first = interrupts[0] if isinstance(interrupts, (tuple, list)) else interrupts
            pending = getattr(first, "value", first)
            if isinstance(pending, dict) and pending.get("intent_id"):
                final_state.apply_response(
                    {
                        "status": "confirmation_required",
                        "output_text": "A write action is waiting for confirmation.",
                        "provider": "",
                        "model": "",
                        "request_id": final_state.execution.request_id,
                    }
                )
                final_state.browser_context = {
                    **final_state.browser_context,
                    "pending_write_confirmation": pending,
                }
                self._adapter.complete_conversation(
                    _load_conversation_run(result.get("conversation_run")),
                    final_state,
                )
                final_state.sync_contract()
        emitted = {
            AgentEventType(item) for item in result.get("emitted_event_types", ())
        }
        return final_state, emitted

    def __call__(self, state: AgentState) -> AgentState:
        final_state, _ = self._invoke(state, emit=None, control=None)
        return final_state

    def run_with_events(
        self,
        state: AgentState,
        emit: GraphEventSink,
        *,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        final_state, emitted = self._invoke(state, emit=emit, control=control)
        self._adapter.emit_compatibility_events(final_state, emitted, emit)
        return final_state

    def resume_with_events(
        self,
        state: AgentState,
        emit: GraphEventSink,
        *,
        control: AgentRunControl | None = None,
    ) -> AgentState:
        """Continue a previously checkpointed run from its latest graph step."""

        final_state, emitted = self._invoke(
            state,
            emit=emit,
            control=control,
            resume=True,
        )
        self._adapter.emit_compatibility_events(final_state, emitted, emit)
        return final_state

    def close(self) -> None:
        self._adapter.close()
        close = getattr(self._react_decision_service, "close", None)
        if callable(close):
            close()


__all__ = [
    "ReadingAgentGraph",
    "ReadingAgentGraphState",
    "ReadingAgentRuntimeContext",
]
