from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from backend.models.agent_react import (
    AgentObservation,
    AgentReActContext,
    AgentReActDecision,
    AgentReActStatus,
    EvidenceSufficiency,
)
from backend.models.agent_runtime import (
    AgentCitationRef,
    AgentConversationContext,
    AgentConversationMessage,
    AgentEvidenceItem,
    AgentExecutionContext,
    AgentPlanContext,
    AgentPlanStep,
    AgentReadingContext,
    AgentRequestContext,
    AgentResponseContext,
    AgentRouteDecision,
    AgentRuntimeProfile,
)
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
    ResolvedKnowledgeScope,
)

CURRENT_AGENT_GRAPH_VERSION = "reading-agent-ma03-v1"
CURRENT_AGENT_STATE_SCHEMA_VERSION = 2
LEGACY_AGENT_GRAPH_VERSION = "reading-agent-v1"
SUPPORTED_AGENT_GRAPH_VERSIONS = frozenset(
    {LEGACY_AGENT_GRAPH_VERSION, CURRENT_AGENT_GRAPH_VERSION}
)


def migrate_agent_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade pre-MA03 checkpoints without accepting an unknown node graph."""

    migrated = dict(payload)
    graph_version = str(migrated.get("graph_version", "") or "").strip()
    if not graph_version:
        graph_version = LEGACY_AGENT_GRAPH_VERSION
    if graph_version not in SUPPORTED_AGENT_GRAPH_VERSIONS:
        raise ValueError(f"unsupported Agent graph_version: {graph_version}")
    schema_version = int(migrated.get("state_schema_version", 1) or 1)
    if schema_version > CURRENT_AGENT_STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported Agent state schema version: {schema_version}")
    migrated["checkpoint_source_graph_version"] = (
        graph_version if graph_version != CURRENT_AGENT_GRAPH_VERSION else ""
    )
    run_id = str(migrated.get("run_id", "") or "").strip()
    if run_id and not str(migrated.get("task_id", "") or "").strip():
        legacy_identity = run_id.removeprefix("run-")
        migrated["task_id"] = f"task-{legacy_identity}"
    migrated.setdefault("runtime_profile", AgentRuntimeProfile.INTERACTIVE.value)
    migrated["graph_version"] = CURRENT_AGENT_GRAPH_VERSION
    migrated["state_schema_version"] = CURRENT_AGENT_STATE_SCHEMA_VERSION
    return migrated


def _run_id() -> str:
    return f"run-{uuid4().hex}"


def _task_id() -> str:
    return f"task-{uuid4().hex}"


def _trace_id() -> str:
    return f"trace-{uuid4().hex}"


def _safe_request_id(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _history_from_context(context: dict[str, Any]) -> list[AgentConversationMessage]:
    raw = context.get("conversation_history", ())
    if not isinstance(raw, (list, tuple)):
        return []

    history: list[AgentConversationMessage] = []
    for item in raw:
        role = ""
        content = ""
        message_id = ""
        if isinstance(item, dict):
            role = str(item.get("role", "") or "").strip()
            content = str(item.get("content", "") or "").strip()
            message_id = str(item.get("message_id", "") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            role = str(item[0] or "").strip()
            content = str(item[1] or "").strip()
        if role not in {"user", "assistant", "system", "tool"} or not content:
            continue
        history.append(
            AgentConversationMessage(
                role=role,  # type: ignore[arg-type]
                content=content,
                message_id=message_id,
            )
        )
    return history


class AgentState(BaseModel):
    """Shared state passed through the Agent execution lifecycle."""

    task_id: str = Field(default_factory=_task_id, min_length=1, max_length=256)
    run_id: str = Field(default_factory=_run_id, min_length=1, max_length=256)
    trace_id: str = Field(default_factory=_trace_id, min_length=1, max_length=256)
    runtime_profile: AgentRuntimeProfile = AgentRuntimeProfile.INTERACTIVE
    session_id: str | None = None
    user_input: str = ""
    selected_text: str = ""
    browser_context: dict[str, Any] = Field(default_factory=dict)
    intent: str | None = None
    planned_action: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)
    ui_mode: str = "assistant"
    graph_version: str = CURRENT_AGENT_GRAPH_VERSION
    state_schema_version: int = CURRENT_AGENT_STATE_SCHEMA_VERSION
    checkpoint_source_graph_version: str = ""
    orchestration_lane: str = "fast"
    orchestration_status: str = "idle"
    orchestration_scope: dict[str, Any] = Field(default_factory=dict)
    orchestration_plan: dict[str, Any] = Field(default_factory=dict)
    orchestration_results: list[dict[str, Any]] = Field(default_factory=list)
    memory_snapshot_ref: str = ""

    execution: AgentExecutionContext = Field(default_factory=AgentExecutionContext)
    conversation: AgentConversationContext = Field(default_factory=AgentConversationContext)
    request: AgentRequestContext = Field(default_factory=AgentRequestContext)
    reading_context: AgentReadingContext = Field(default_factory=AgentReadingContext)
    route: AgentRouteDecision = Field(default_factory=AgentRouteDecision)
    plan: AgentPlanContext = Field(default_factory=AgentPlanContext)
    react: AgentReActContext = Field(default_factory=AgentReActContext)
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)
    response_state: AgentResponseContext = Field(default_factory=AgentResponseContext)
    knowledge_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy.AUTO
    knowledge_decision: KnowledgeAccessDecision | None = None
    knowledge_scope: ResolvedKnowledgeScope = Field(default_factory=ResolvedKnowledgeScope)
    retrieval_attempt_count: int = Field(default=0, ge=0)
    knowledge_search_count: int = Field(default=0, ge=0)
    knowledge_read_count: int = Field(default=0, ge=0)
    evidence_sufficient: bool | None = None
    evidence_sufficiency: EvidenceSufficiency | None = None

    @model_validator(mode="after")
    def initialize_contracts(self) -> AgentState:
        return self.sync_contract()

    def sync_contract(self) -> AgentState:
        context = dict(self.browser_context)
        raw_policy = context.get("knowledge_access_policy")
        if raw_policy is not None:
            try:
                self.knowledge_policy = KnowledgeAccessPolicy(raw_policy)
            except ValueError:
                self.knowledge_policy = KnowledgeAccessPolicy.AUTO
        raw_decision = context.get("knowledge_decision")
        if isinstance(raw_decision, dict):
            try:
                self.knowledge_decision = KnowledgeAccessDecision.model_validate(
                    raw_decision
                )
            except ValueError:
                self.knowledge_decision = None
        raw_scope = context.get("knowledge_scope")
        if isinstance(raw_scope, dict):
            try:
                self.knowledge_scope = ResolvedKnowledgeScope.model_validate(raw_scope)
            except ValueError:
                self.knowledge_scope = ResolvedKnowledgeScope()
        request_id = _safe_request_id(
            self.response.get("request_id", context.get("request_id", 0))
        )
        explicit_route = (
            self.route
            if self.route.source in {"deterministic", "semantic_router", "planner"}
            else None
        )
        preserve_multi_step = (
            self.plan.mode == "multi_step"
            and explicit_route is not None
            and explicit_route.kind == "complex"
        )

        self.execution = AgentExecutionContext(
            task_id=self.task_id,
            run_id=self.run_id,
            trace_id=self.trace_id,
            session_id=str(self.session_id or ""),
            request_id=request_id,
            runtime_profile=self.runtime_profile,
        )
        mode = str(context.get("conversation_context_mode", "reading") or "reading").strip().lower()
        if mode not in {"general", "reading"}:
            mode = "reading"
        self.conversation = AgentConversationContext(
            conversation_id=str(context.get("conversation_id", "") or "").strip(),
            history=_history_from_context(context),
            user_message_id=str(context.get("conversation_user_message_id", "") or "").strip(),
            assistant_message_id=str(
                context.get("conversation_assistant_message_id", "") or ""
            ).strip(),
            context_mode=mode,  # type: ignore[arg-type]
        )
        self.request = AgentRequestContext(
            user_input=self.user_input,
            style=str(context.get("style", "academic") or "academic"),
        )
        self.reading_context = AgentReadingContext(
            source_text=self.selected_text,
            translated_text=str(context.get("translated_text", "") or ""),
            source_language=str(context.get("source_language", "auto") or "auto"),
            target_language=str(context.get("target_language", "zh-CN") or "zh-CN"),
            resource_url=str(context.get("resource_url", "") or ""),
            resource_title=str(context.get("resource_title", "") or ""),
            section_heading=str(context.get("section_heading", "") or ""),
            context_before=str(context.get("context_before", "") or ""),
            context_after=str(context.get("context_after", "") or ""),
            source_kind=str(context.get("source_kind", "desktop") or "desktop"),
        )

        action = str(self.planned_action.get("action", "") or "").strip()
        tool_name = str(self.planned_action.get("tool_name", "") or "").strip()
        arguments = {
            str(key): str(value)
            for key, value in dict(self.planned_action.get("arguments", {}) or {}).items()
        }
        if preserve_multi_step:
            pass
        elif action == "tool" and tool_name:
            step_status = "completed" if any(
                str(item.get("tool_name", "") or item.get("name", "") or "") == tool_name
                for item in self.tool_results
                if isinstance(item, dict)
            ) else "pending"
            if explicit_route is None:
                self.route = AgentRouteDecision(
                    kind="tool",
                    source="legacy_planner",
                    intent=str(self.intent or tool_name),
                    tool_name=tool_name,
                    user_visible_reason=str(
                        self.planned_action.get("user_visible_reason", "") or ""
                    ),
                    arguments=arguments,
                )
            self.plan = AgentPlanContext(
                goal=str(self.planned_action.get("user_visible_reason", "") or ""),
                mode="single_step",
                steps=[
                    AgentPlanStep(
                        step_id="step-1",
                        tool_name=tool_name,
                        arguments=dict(arguments),
                        status=step_status,  # type: ignore[arg-type]
                    )
                ],
                current_step_id="" if step_status == "completed" else "step-1",
            )
        elif action == "answer":
            if explicit_route is None:
                self.route = AgentRouteDecision(
                    kind="answer",
                    source="legacy_planner",
                    intent=str(self.intent or "answer"),
                    user_visible_reason=str(
                        self.planned_action.get("user_visible_reason", "") or ""
                    ),
                )
            self.plan = AgentPlanContext()
        else:
            if explicit_route is None:
                self.route = AgentRouteDecision(
                    kind="unresolved",
                    source="none",
                    intent=str(self.intent or ""),
                )
            self.plan = AgentPlanContext()

        status = str(self.response.get("status", "") or "").strip()
        if status not in {
            "completed",
            "confirmation_required",
            "failed",
            "cancelled",
        }:
            status = "idle"
        self.response_state = AgentResponseContext(
            status=status,  # type: ignore[arg-type]
            output_text=str(self.response.get("output_text", "") or ""),
            provider=str(self.response.get("provider", "") or ""),
            model=str(self.response.get("model", "") or ""),
            request_id=request_id,
            ui_mode=self.ui_mode,
        )
        return self

    def apply_reading_context(self, context: dict[str, Any]) -> AgentState:
        self.browser_context = dict(context)
        if "source_text" in context:
            self.selected_text = str(context.get("source_text", "") or "")
        return self.sync_contract()

    def apply_conversation(
        self,
        *,
        conversation_id: str,
        history: tuple[tuple[str, str], ...] | list[tuple[str, str]],
        user_message_id: str = "",
        assistant_message_id: str = "",
        context_mode: str = "reading",
    ) -> AgentState:
        context = dict(self.browser_context)
        context["conversation_id"] = str(conversation_id or "").strip()
        context["conversation_history"] = [
            {"role": str(role), "content": str(content)}
            for role, content in history
            if str(role).strip() and str(content).strip()
        ]
        context["conversation_user_message_id"] = str(user_message_id or "").strip()
        context["conversation_assistant_message_id"] = str(
            assistant_message_id or ""
        ).strip()
        context["conversation_context_mode"] = (
            context_mode if context_mode in {"general", "reading"} else "reading"
        )
        self.browser_context = context
        return self.sync_contract()

    def apply_plan(self, plan: dict[str, Any]) -> AgentState:
        self.planned_action = dict(plan)
        action = str(self.planned_action.get("action", "") or "")
        tool_name = str(self.planned_action.get("tool_name", "") or "")
        self.intent = tool_name if action == "tool" and tool_name else "answer"
        return self.sync_contract()

    def apply_multi_step_plan(
        self,
        plan: AgentPlanContext | dict[str, Any],
    ) -> AgentState:
        self.plan = (
            plan
            if isinstance(plan, AgentPlanContext)
            else AgentPlanContext.model_validate(plan)
        )
        if self.plan.mode != "multi_step":
            raise ValueError("apply_multi_step_plan requires mode='multi_step'.")
        self.planned_action = {
            "action": "answer",
            "tool_name": "",
            "user_visible_reason": self.plan.goal,
            "arguments": {},
        }
        self.intent = "complex"
        return self.sync_contract()

    def apply_orchestration(
        self,
        *,
        lane: str,
        status: str,
        scope: dict[str, Any],
        plan: dict[str, Any] | None,
        results: list[dict[str, Any]],
        memory_snapshot_ref: str = "",
    ) -> AgentState:
        self.graph_version = CURRENT_AGENT_GRAPH_VERSION
        self.state_schema_version = CURRENT_AGENT_STATE_SCHEMA_VERSION
        self.orchestration_lane = str(lane or "fast")
        self.orchestration_status = str(status or "idle")
        self.orchestration_scope = dict(scope)
        self.orchestration_plan = dict(plan or {})
        self.orchestration_results = [dict(item) for item in results]
        self.memory_snapshot_ref = str(memory_snapshot_ref or "")
        if self.orchestration_plan:
            self.planned_action = {
                "action": "answer",
                "tool_name": "",
                "user_visible_reason": "Execute the validated research task plan.",
                "arguments": {
                    "orchestration_plan_id": str(
                        self.orchestration_plan.get("plan_id", "") or ""
                    )
                },
            }
            self.intent = "complex"
        return self.sync_contract()

    def mark_plan_step(self, step_id: str, status: str) -> AgentState:
        valid = {"pending", "running", "completed", "failed", "skipped"}
        if status not in valid:
            raise ValueError(f"Unsupported plan step status: {status}")
        found = False
        steps: list[AgentPlanStep] = []
        for step in self.plan.steps:
            if step.step_id == step_id:
                found = True
                steps.append(step.model_copy(update={"status": status}))
            else:
                steps.append(step)
        if not found:
            raise KeyError(f"Unknown plan step: {step_id}")

        current = ""
        if status != "running":
            current = next(
                (step.step_id for step in steps if step.status == "pending"),
                "",
            )
        else:
            current = step_id
        self.plan = self.plan.model_copy(
            update={"steps": steps, "current_step_id": current}
        )
        return self.sync_contract()

    def apply_route(
        self,
        route: AgentRouteDecision | dict[str, Any],
    ) -> AgentState:
        self.route = (
            route
            if isinstance(route, AgentRouteDecision)
            else AgentRouteDecision.model_validate(route)
        )
        if self.route.intent:
            self.intent = self.route.intent
        elif self.route.tool_name:
            self.intent = self.route.tool_name
        elif self.route.kind == "answer":
            self.intent = "answer"
        elif self.route.kind == "complex":
            self.intent = "complex"
        return self.sync_contract()

    def start_react(self) -> AgentState:
        """Start a fresh ReAct context without affecting existing plan execution."""

        self.react = AgentReActContext(status="running")
        return self.sync_contract()

    def record_react_decision(
        self,
        decision: AgentReActDecision | dict[str, Any],
    ) -> AgentState:
        item = (
            decision
            if isinstance(decision, AgentReActDecision)
            else AgentReActDecision.model_validate(decision)
        )
        if item.iteration <= self.react.iteration:
            raise ValueError("ReAct decision iteration must advance monotonically")
        decisions = [*self.react.decisions, item]
        self.react = self.react.model_copy(
            update={
                "status": "running",
                "iteration": item.iteration,
                "decisions": decisions,
                "last_decision": item,
            }
        )
        return self.sync_contract()

    def record_react_observation(
        self,
        observation: AgentObservation | dict[str, Any],
    ) -> AgentState:
        item = (
            observation
            if isinstance(observation, AgentObservation)
            else AgentObservation.model_validate(observation)
        )
        if item.iteration > self.react.iteration:
            raise ValueError("ReAct observation cannot be ahead of the current iteration")
        if not any(
            decision.iteration == item.iteration
            and decision.kind == "tool"
            and decision.tool_name == item.tool_name
            for decision in self.react.decisions
        ):
            raise ValueError("ReAct observation must match a recorded tool decision")
        observations = [*self.react.observations, item]
        self.react = self.react.model_copy(update={"observations": observations})
        return self.sync_contract()

    def mark_react_status(self, status: AgentReActStatus) -> AgentState:
        self.react = self.react.model_copy(update={"status": status})
        return self.sync_contract()

    def record_tool_call(self, call: dict[str, Any]) -> AgentState:
        self.tool_calls.append(dict(call))
        return self.sync_contract()

    def record_tool_result(self, result: dict[str, Any]) -> AgentState:
        self.tool_results.append(dict(result))
        return self.sync_contract()

    def apply_response(self, response: dict[str, Any]) -> AgentState:
        self.response = dict(response)
        return self.sync_contract()


__all__ = [
    "CURRENT_AGENT_GRAPH_VERSION",
    "CURRENT_AGENT_STATE_SCHEMA_VERSION",
    "LEGACY_AGENT_GRAPH_VERSION",
    "SUPPORTED_AGENT_GRAPH_VERSIONS",
    "AgentState",
    "migrate_agent_state_payload",
]
