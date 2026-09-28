from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from backend.agent_core.orchestration.agent_registry import (
    AgentRegistry,
    build_default_agent_registry,
)
from backend.agent_core.orchestration.roles import RoleRegistry
from backend.agent_core.orchestration.validation import (
    TaskPlanValidationError,
    validate_task_plan,
)
from backend.agent_core.reliability import AgentRunControl
from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolModel,
    EmptyToolResultData,
    typed_tool_definition,
)
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_tasks import (
    ScopeContext,
    TaskRole,
    TaskSpec,
    ValidatedTaskPlan,
)
from backend.models.agent_tools import AgentRunRequest
from backend.sandbox.models import SandboxExecutionResult
from backend.services.agent_tool_registry import AgentToolRegistry
from backend.services.product_agent_service import ProductAgentService
from backend.services.product_agent_tool_port import (
    ProductAgentToolRuntimePort,
)


class _EchoArgs(AgentToolModel):
    text: str


class _EchoResult(AgentToolModel):
    echoed: str


class _NoCallChat:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected chat-service call: {name}")


def _external_tool(name: str, executor, *, effect: str = "compute"):
    return typed_tool_definition(
        name=name,
        title=name,
        description="Server configured test capability.",
        category="test",
        effect=effect,
        requires_reading_context=False,
        requires_confirmation=effect == "write",
        args_model=_EchoArgs,
        result_model=_EchoResult,
        executor=executor,
        retry_policy="never" if effect == "write" else "safe",
    )


def _scope() -> ScopeContext:
    return ScopeContext.issue(
        scope_revision="fixture-v1",
        allowed_document_ids=["doc-1"],
        allowed_note_ids=["note-1"],
    )


def _port(
    *,
    allowed_tools: set[str],
    scope: ScopeContext,
    definitions=(),
    tool_registry: AgentToolRegistry | None = None,
    write_confirmation_provider=None,
):
    defaults = build_default_agent_registry()
    document = replace(
        defaults.for_role(TaskRole.DOCUMENT),
        allowed_tools=frozenset(allowed_tools),
        default_tools=tuple(
            tool
            for tool in defaults.for_role(TaskRole.DOCUMENT).default_tools
            if tool in allowed_tools
        ),
    )
    agent_registry = AgentRegistry((document,))
    task = TaskSpec(
        task_id="task-1",
        role=TaskRole.DOCUMENT,
        objective="Run the test capability",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope.scope_ref,
        allowed_tools=sorted(allowed_tools),
    )
    tool_registry = tool_registry or AgentToolRegistry(
        external_tool_definitions=tuple(definitions)
    )
    product_service = ProductAgentService(
        registry=tool_registry,
        chat_service=_NoCallChat(),  # type: ignore[arg-type]
    )
    return ProductAgentToolRuntimePort(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        product_agent_service=product_service,
        task_resolver=lambda _run_id, task_id: task
        if task_id == task.task_id
        else None,
        scope_resolver=lambda _run_id, _task_id, scope_ref: scope
        if scope_ref == scope.scope_ref
        else None,
        context_provider=lambda _task, _scope: {"source_text": ""},
        write_confirmation_provider=write_confirmation_provider,
    ), tool_registry


def test_allowed_external_tool_runs_through_typed_product_boundary():
    calls = []

    def execute(_context, args):
        calls.append(args.text)
        return AgentToolExecutionResult(
            tool_name="fixture_echo",
            output_text=args.text,
            effect="compute",
            data={"echoed": args.text},
        )

    scope = _scope()
    port, _registry = _port(
        allowed_tools={"fixture_echo"},
        scope=scope,
        definitions=[_external_tool("fixture_echo", execute)],
    )

    result = port.execute(
        run_id="run-1",
        task_id="task-1",
        agent_id="document",
        tool_name="fixture_echo",
        arguments={"text": "synthetic"},
        scope_ref=scope.scope_ref,
        control=AgentRunControl(),
    )

    assert result.output_text == "synthetic"
    assert result.data == {"echoed": "synthetic"}
    assert calls == ["synthetic"]


def test_agent_allowlist_rejects_tool_before_executor_runs():
    calls = []
    definition = _external_tool(
        "fixture_echo",
        lambda _context, args: calls.append(args.text),
    )
    scope = _scope()
    port, _registry = _port(allowed_tools=set(), scope=scope, definitions=[definition])

    with pytest.raises(PermissionError, match="not allowed"):
        port.execute(
            run_id="run-1", task_id="task-1", agent_id="document",
            tool_name="fixture_echo", arguments={"text": "no"},
            scope_ref=scope.scope_ref, control=AgentRunControl(),
        )

    assert calls == []


def test_forged_scope_reference_is_rejected_before_executor_runs():
    calls = []
    definition = _external_tool(
        "fixture_echo",
        lambda _context, args: calls.append(args.text),
    )
    scope = _scope()
    port, _registry = _port(
        allowed_tools={"fixture_echo"}, scope=scope, definitions=[definition]
    )

    with pytest.raises(PermissionError, match="scope"):
        port.execute(
            run_id="run-1", task_id="task-1", agent_id="document",
            tool_name="fixture_echo", arguments={"text": "no"},
            scope_ref="scope:forged", control=AgentRunControl(),
        )

    assert calls == []


def test_external_tool_definitions_reject_duplicate_empty_name_and_bad_schema():
    definition = _external_tool("fixture_echo", lambda _context, _args: None)
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        AgentToolRegistry(external_tool_definitions=(definition, definition))

    empty_name = _external_tool("", lambda _context, _args: None)
    with pytest.raises(ValueError, match="name"):
        AgentToolRegistry(external_tool_definitions=(empty_name,))

    malformed_schema = definition.__class__(
        spec=replace(definition.spec, input_schema={"text": []}),
        args_model=definition.args_model,
        result_model=definition.result_model,
        executor=definition.executor,
        retry_policy=definition.retry_policy,
    )
    with pytest.raises(ValueError, match="schema"):
        AgentToolRegistry(external_tool_definitions=(malformed_schema,))


def test_sandbox_tools_are_absent_when_no_sandbox_manager_is_injected():
    registry = AgentToolRegistry(sandbox_manager=None)

    assert registry.get_tool("python_execute") is None
    assert registry.get_tool("command_execute") is None


def test_enabled_sandbox_tool_uses_the_same_worker_admission_port():
    class FakeSandboxManager:
        def __init__(self):
            self.codes = []

        def execute_python(self, code, **_kwargs):
            self.codes.append(code)
            return SandboxExecutionResult(
                sandbox_id="sandbox-test",
                status="succeeded",
                exit_code=0,
                stdout="2",
                duration_ms=1,
            )

    manager = FakeSandboxManager()
    registry = AgentToolRegistry(sandbox_manager=manager)
    scope = _scope()
    port, _registry = _port(
        allowed_tools={"python_execute"},
        scope=scope,
        tool_registry=registry,
    )

    result = port.execute(
        run_id="run-1", task_id="task-1", agent_id="document",
        tool_name="python_execute", arguments={"code": "print(1 + 1)"},
        scope_ref=scope.scope_ref, control=AgentRunControl(),
    )

    assert result.output_text == "2"
    assert manager.codes == ["print(1 + 1)"]


def test_write_tool_without_server_confirmation_never_runs():
    calls = []
    definition = _external_tool(
        "fixture_write",
        lambda _context, args: calls.append(args.text),
        effect="write",
    )
    scope = _scope()
    port, _registry = _port(
        allowed_tools={"fixture_write"}, scope=scope, definitions=[definition]
    )

    with pytest.raises(PermissionError, match="confirmation"):
        port.execute(
            run_id="run-1", task_id="task-1", agent_id="document",
            tool_name="fixture_write", arguments={"text": "write"},
            scope_ref=scope.scope_ref, control=AgentRunControl(),
        )

    assert calls == []

    with pytest.raises(TypeError, match="confirmed_write_tools"):
        port.execute(
            run_id="run-1", task_id="task-1", agent_id="document",
            tool_name="fixture_write", arguments={"text": "write"},
            scope_ref=scope.scope_ref, control=AgentRunControl(),
            confirmed_write_tools=["fixture_write"],
        )


def test_server_write_confirmation_provider_is_consumed_once():
    calls = []
    definition = _external_tool(
        "fixture_write",
        lambda _context, args: (
            calls.append(args.text)
            or AgentToolExecutionResult(
                tool_name="fixture_write",
                output_text="saved",
                effect="write",
                data={"echoed": args.text},
            )
        ),
        effect="write",
    )
    approvals = [True]
    scope = _scope()
    port, _registry = _port(
        allowed_tools={"fixture_write"},
        scope=scope,
        definitions=[definition],
        write_confirmation_provider=lambda _run, _task, _tool: (
            approvals.pop(0) if approvals else False
        ),
    )
    request = {
        "run_id": "run-1",
        "task_id": "task-1",
        "agent_id": "document",
        "tool_name": "fixture_write",
        "arguments": {"text": "single write"},
        "scope_ref": scope.scope_ref,
        "control": AgentRunControl(),
    }

    assert port.execute(**request).output_text == "saved"
    with pytest.raises(PermissionError, match="confirmation"):
        port.execute(**request)
    assert calls == ["single write"]


def test_python_and_command_trace_summaries_do_not_include_raw_arguments():
    registry = AgentToolRegistry()
    raw_code = "print('private payload')"
    raw_argv = ["python", "-c", "print('private payload')"]
    summaries = {
        "python": registry.trace_arguments("python_execute", {"code": raw_code}),
        "command": registry.trace_arguments("command_execute", {"argv": raw_argv}),
    }
    encoded = json.dumps(summaries, ensure_ascii=False)

    assert summaries["python"]["code_chars"] == len(raw_code)
    assert summaries["command"]["argv_count"] == len(raw_argv)
    assert raw_code not in encoded
    assert "private payload" not in encoded


def test_tool_spec_validation_preserves_typed_numeric_and_boolean_arguments():
    class TypedArgs(AgentToolModel):
        count: int
        enabled: bool

    definition = typed_tool_definition(
        name="fixture_typed",
        title="Typed",
        description="Typed arguments.",
        category="test",
        effect="compute",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=TypedArgs,
        result_model=EmptyToolResultData,
        executor=lambda _context, _args: AgentToolExecutionResult(
            tool_name="fixture_typed", output_text="ok", effect="compute"
        ),
    )

    assert definition.spec.validate_planner_arguments(
        {"count": 3, "enabled": True}
    ) == {"count": 3, "enabled": True}
    with pytest.raises(ValueError, match="integer"):
        definition.spec.validate_planner_arguments(
            {"count": "3", "enabled": True}
        )


def test_plan_cannot_reference_a_tool_missing_from_server_registry():
    scope = _scope()
    defaults = build_default_agent_registry()
    document = replace(
        defaults.for_role(TaskRole.DOCUMENT),
        allowed_tools=frozenset({"server_only_but_unregistered"}),
        default_tools=(),
    )
    plan = ValidatedTaskPlan(
        plan_id="plan-1",
        scope_ref=scope.scope_ref,
        tasks=[
            TaskSpec(
                task_id="task-1",
                role=TaskRole.DOCUMENT,
                objective="Use the configured tool",
                required=True,
                expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
                scope_ref=scope.scope_ref,
                allowed_tools=["server_only_but_unregistered"],
            )
        ],
    )

    with pytest.raises(TaskPlanValidationError, match="not configured on the server"):
        validate_task_plan(
            plan,
            scope=scope,
            role_registry=RoleRegistry(agent_registry=AgentRegistry((document,))),
            tool_registry=AgentToolRegistry(),
        )


def test_user_request_does_not_expose_a_tool_registration_field():
    assert "external_tool_definitions" not in AgentRunRequest.model_fields
    request = AgentRunRequest.model_validate(
        {
            "user_message": "Use an external capability.",
            "external_tool_definitions": [{"name": "untrusted"}],
        }
    )

    assert not hasattr(request, "external_tool_definitions")
