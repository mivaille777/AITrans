"""Governed test calls. Cancellation never claims to kill a Python worker."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from uuid import uuid4

from pydantic import ValidationError

from backend.agent_core.reliability import AgentExecutionPolicy, AgentRunControl
from backend.agent_tools.base import AgentToolInvocationContext
from backend.models.sandbox_permissions import PermissionDecision, PermissionRequest
from backend.models.tool_test import ToolTestRequest, ToolTestRun
from backend.services.agent_tool_execution_service import AgentToolExecutionService
from backend.services.sandbox_approval_service import (
    SandboxApprovalError,
    SandboxApprovalService,
)
from backend.services.tool_management_service import ToolManagementError, fingerprint

_READING_FIELDS = {
    "source_text",
    "translated_text",
    "source_language",
    "target_language",
    "resource_url",
    "resource_title",
    "section_heading",
    "context_before",
    "context_after",
    "source_kind",
    "style",
    "ai_content",
    "knowledge_item_id",
    "knowledge_writeback_type",
    "knowledge_writeback_operation",
    "knowledge_relation_type",
}
_FINAL = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


def now():
    return datetime.now(UTC).isoformat()


class ToolTestService:
    def __init__(
        self,
        management,
        *,
        approvals=None,
        library=None,
        research=None,
        filesystem=None,
        store=None,
    ):
        self.management = management
        self.registry = management.registry
        self.approvals = approvals or SandboxApprovalService()
        self.library, self.research, self.filesystem = library, research, filesystem
        self._lock = RLock()
        self._runs = {}
        self._requests = {}
        self._idempotency = {}
        self._controls = {}
        self._closed = False
        self.store = store
        if store:
            store.recover()

    def validate(self, tool_id, request: ToolTestRequest):
        detail = self.management.detail(tool_id)
        if not detail.effective_enabled:
            raise ToolManagementError(
                "tool_unavailable",
                detail.unavailable_reason or "Tool is disabled.",
                403,
            )
        if request.stream_output and not detail.execution_capabilities.get(
            "supports_output_stream"
        ):
            raise ToolManagementError(
                "stream_unsupported", "This executor does not stream output."
            )
        definition = self.registry.get_definition(detail.name)
        unknown = set(request.arguments) - set(definition.args_model.model_fields)
        if unknown:
            raise ToolManagementError(
                "invalid_arguments",
                "Unknown or reserved arguments.",
                fields=[
                    {"path": key, "message": "Unknown argument"}
                    for key in sorted(unknown)
                ],
            )
        try:
            args = definition.args_model.model_validate(
                request.arguments, strict=True
            ).model_dump(mode="json")
        except ValidationError as exc:
            raise ToolManagementError(
                "invalid_arguments",
                "Input parameters are invalid.",
                fields=[
                    {"path": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
                    for e in exc.errors()
                ],
            ) from exc
        selection = request.context_selection
        if set(selection.reading_context) - _READING_FIELDS:
            raise ToolManagementError(
                "reserved_context",
                "Reading context contains server-owned or unknown fields.",
            )
        context = dict(selection.reading_context)
        ids = list(dict.fromkeys(selection.knowledge_document_ids))
        if selection.research_workspace_id:
            profile = (
                self.research.get(selection.research_workspace_id)
                if self.research
                else None
            )
            if profile is None:
                raise ToolManagementError(
                    "workspace_not_found", "Research workspace was not found.", 404
                )
            if set(ids) - set(profile.document_ids):
                raise ToolManagementError(
                    "scope_violation",
                    "Documents are outside the research workspace.",
                    403,
                )
            context["workspace_id"] = selection.research_workspace_id
        if selection.filesystem_workspace_id:
            if self.filesystem is None:
                raise ToolManagementError(
                    "filesystem_unavailable",
                    "Filesystem workspace service unavailable.",
                    503,
                )
            try:
                self.filesystem.active_root_path(selection.filesystem_workspace_id)
            except Exception as exc:
                raise ToolManagementError(
                    "filesystem_unavailable",
                    "Filesystem workspace is unavailable.",
                    403,
                ) from exc
            context["filesystem_workspace_id"] = selection.filesystem_workspace_id
        if (
            "filesystem_workspace" in detail.context_requirements
            and not selection.filesystem_workspace_id
        ):
            raise ToolManagementError(
                "context_required", "Select a filesystem workspace."
            )
        if "reading_context" in detail.context_requirements and not context.get(
            "source_text"
        ):
            raise ToolManagementError(
                "context_required", "Source text is required in reading context."
            )
        if "knowledge_scope" in detail.context_requirements:
            if not ids:
                raise ToolManagementError(
                    "context_required",
                    "Select explicit knowledge document IDs; global search is not allowed.",
                )
            for doc_id in ids:
                if self.library is None or self.library.get_document(doc_id) is None:
                    raise ToolManagementError(
                        "document_not_found",
                        "Selected knowledge document was not found.",
                        404,
                    )
            # Arguments may narrow the trusted scope, never expand it.
            scope_args = {**detail.configuration.get("fixed_arguments", {}), **args}
            requested = set(scope_args.get("document_ids", [])) | {
                x.strip()
                for x in str(scope_args.get("document_scope", ""))
                .replace("\n", ",")
                .split(",")
                if x.strip()
            }
            if requested - set(ids):
                raise ToolManagementError(
                    "scope_violation", "Arguments cannot expand document scope.", 403
                )
        context["knowledge_document_ids"] = ids
        context["knowledge_scope_allow_global"] = False
        try:
            context = AgentToolInvocationContext.model_validate(
                context, strict=True
            ).model_dump(mode="json", exclude_unset=True)
        except ValidationError as exc:
            raise ToolManagementError(
                "invalid_context", "Reading context is invalid."
            ) from exc
        return detail, args, context

    def create(self, tool_id, request):
        digest = fingerprint(
            [tool_id, request.model_dump(exclude={"client_request_id"})]
        )
        with self._lock:
            if self.store:
                existing = self.store.find(tool_id, request.client_request_id, digest)
                if existing:
                    return self.get(tool_id, existing.test_run_id)
            key = (tool_id, request.client_request_id)
            if key in self._idempotency:
                old_digest, run_id = self._idempotency[key]
                if digest != old_digest:
                    raise ToolManagementError(
                        "idempotency_conflict",
                        "Request ID was already used with different input.",
                        409,
                    )
                return self.get(tool_id, run_id)
            if self._closed:
                raise ToolManagementError(
                    "service_closed", "Test service is shutting down.", 503
                )
            detail, args, context = self.validate(tool_id, request)
            run_id, call_id = "test_" + uuid4().hex, "call_" + uuid4().hex
            run = ToolTestRun(
                test_run_id=run_id,
                tool_id=tool_id,
                tool_name=detail.name,
                trace_id="trace_" + uuid4().hex,
                tool_call_id=call_id,
                created_at=now(),
                updated_at=now(),
            )
            context.update(run_id=run_id, trace_id=run.trace_id, tool_call_id=call_id)
            if self.store:
                run, owned = self.store.claim(run, request.client_request_id, digest)
                if not owned:
                    return run
            self._runs[run_id] = run
            self._requests[run_id] = (request, args, context, detail.revision)
            self._idempotency[key] = (digest, run_id)
            if detail.permissions.get("requires_confirmation"):
                scope = {
                    "action": "tool.execute",
                    "target": tool_id,
                    "input_hash": fingerprint([args, context]),
                    "revision": detail.revision,
                }
                approval = self.approvals.create_approval(
                    PermissionRequest(
                        action="tool.execute",
                        target=tool_id,
                        reason="Explicit Tools test write approval",
                        tool_name=detail.name,
                        run_id=run_id,
                        tool_call_id=call_id,
                    ),
                    PermissionDecision(
                        decision="approval_required",
                        reason_code="write_confirmation_required",
                        reason="This tool requires confirmation.",
                        granted_scope=scope,
                    ),
                )
                self._update(
                    run_id,
                    status="awaiting_approval",
                    approval_id=approval.approval_id,
                    approval_summary={
                        "tool": detail.name,
                        "arguments": args,
                        "context_selection": request.context_selection.model_dump(),
                        "revision": detail.revision,
                        "expires_at": approval.expires_at.isoformat(),
                    },
                )
            else:
                self._start(run_id, confirmed=False)
            return self.get(tool_id, run_id)

    def get(self, tool_id, run_id):
        with self._lock:
            run = self._runs.get(run_id) or (
                self.store.get(tool_id, run_id) if self.store else None
            )
            if run is None or run.tool_id != tool_id:
                raise ToolManagementError(
                    "test_not_found", "Test run was not found.", 404
                )
            self._runs[run_id] = run
            if run.status == "awaiting_approval":
                try:
                    if self.approvals.get(run.approval_id).status == "expired":
                        self._update(
                            run_id,
                            status="failed",
                            execution_state="stopped",
                            finished_at=now(),
                            error={
                                "code": "approval_expired",
                                "message": "Approval expired. Create a new test.",
                            },
                        )
                except SandboxApprovalError:
                    self._update(
                        run_id,
                        status="interrupted",
                        execution_state="stopped",
                        finished_at=now(),
                    )
            return self._runs[run_id].model_copy(deep=True)

    def approve(self, tool_id, run_id, approval_id):
        with self._lock:
            run = self.get(tool_id, run_id)
            if run.status != "awaiting_approval" or run.approval_id != approval_id:
                raise ToolManagementError(
                    "approval_binding",
                    "Approval does not match this pending test.",
                    409,
                )
            request, args, context, revision = self._requests[run_id]
            detail, _, current_context = self.validate(tool_id, request)
            if detail.revision != revision or fingerprint(
                {
                    **current_context,
                    "run_id": run_id,
                    "trace_id": run.trace_id,
                    "tool_call_id": run.tool_call_id,
                }
            ) != fingerprint(context):
                raise ToolManagementError(
                    "approval_stale",
                    "Configuration or context changed. Create a new test.",
                    409,
                )
            self.approvals.approve(approval_id)
            self.approvals.consume_grant(
                approval_id,
                action="tool.execute",
                scope={
                    "action": "tool.execute",
                    "target": tool_id,
                    "input_hash": fingerprint([args, context]),
                    "revision": revision,
                },
                run_id=run_id,
                tool_call_id=run.tool_call_id,
            )
            self._start(run_id, confirmed=True)
            return self.get(tool_id, run_id)

    def cancel(self, tool_id, run_id):
        with self._lock:
            run = self.get(tool_id, run_id)
            if run.status not in _FINAL:
                control = self._controls.get(run_id)
                if control:
                    control.cancel()
                if run.status == "awaiting_approval":
                    self.approvals.deny(run.approval_id)
                self._update(
                    run_id,
                    status="cancelled",
                    execution_state="running"
                    if run.execution_state == "running"
                    else "stopped",
                    finished_at=now(),
                    error={
                        "code": "cancelled",
                        "message": "Response cancelled. An active executor may continue; do not repeat uncertain writes.",
                    },
                )
            return self.get(tool_id, run_id)

    def _update(self, run_id, **values):
        with self._lock:
            self._runs[run_id] = self._runs[run_id].model_copy(
                update={**values, "updated_at": now()}
            )
            if self.store:
                self.store.save(self._runs[run_id])
                if self._runs[run_id].finished_at:
                    self._requests.pop(run_id, None)
                    for old_id in self.store.prune():
                        self._runs.pop(old_id, None)
                        self._requests.pop(old_id, None)
                        self._idempotency = {
                            key: value
                            for key, value in self._idempotency.items()
                            if value[1] != old_id
                        }

    def _start(self, run_id, *, confirmed):
        run = self._runs[run_id]
        request, args, context, revision = self._requests[run_id]
        timeout = min(
            request.timeout_seconds,
            float(self.management.detail(run.tool_id).limits["timeout_seconds"]),
        )
        control = AgentRunControl(
            AgentExecutionPolicy(
                total_timeout_seconds=timeout,
                tool_timeout_seconds=timeout,
                max_safe_retries=0,
            )
        )
        self._controls[run_id] = control
        self._update(run_id, status="running", execution_state="running")
        physical_done = Event()
        parent = self

        class TrackedRegistry:
            def get_definition(self, name):
                return parent.registry.get_definition(name)

            def execute(self, name, **payload):
                try:
                    control.checkpoint("test_executor")
                    if parent.management.detail(run.tool_id).revision != revision:
                        raise PermissionError(
                            "Tool configuration changed before execution."
                        )
                    parent.validate(run.tool_id, request)
                    return parent.registry.execute(name, **payload)
                finally:
                    physical_done.set()
                    with parent._lock:
                        if parent._runs[run_id].status in _FINAL:
                            parent._update(run_id, execution_state="stopped")

        def worker():
            try:
                result = AgentToolExecutionService(TrackedRegistry()).execute(
                    run.tool_name,
                    {**args, **context},
                    control=control,
                    run_id=run_id,
                    step_id="tools_test",
                    write_confirmed=confirmed,
                    tool_call_id=run.tool_call_id,
                )
                serialized = json.dumps(asdict(result), ensure_ascii=False, default=str)
                truncated = len(serialized.encode()) > 256 * 1024
                data = (
                    {"preview": serialized[:64000]}
                    if truncated
                    else json.loads(serialized)
                )
                with self._lock:
                    if self._runs[run_id].status not in _FINAL:
                        self._update(
                            run_id,
                            status="succeeded",
                            execution_state="stopped",
                            result=data,
                            result_truncated=truncated,
                            finished_at=now(),
                            elapsed_ms=control.elapsed_ms,
                        )
            except Exception as exc:  # noqa: BLE001 - record executor failure in test lifecycle
                with self._lock:
                    if self._runs[run_id].status not in _FINAL:
                        status = (
                            "timed_out" if control.remaining_seconds <= 0 else "failed"
                        )
                        self._update(
                            run_id,
                            status=status,
                            execution_state="stopped"
                            if physical_done.is_set()
                            else "unknown",
                            error={"code": status, "message": str(exc)[:2000]},
                            finished_at=now(),
                            elapsed_ms=control.elapsed_ms,
                        )
            finally:
                self._controls.pop(run_id, None)

        def deadline():
            if not physical_done.wait(timeout):
                with self._lock:
                    if self._runs[run_id].status not in _FINAL:
                        control.cancel()
                        self._update(
                            run_id,
                            status="timed_out",
                            execution_state="running",
                            finished_at=now(),
                            elapsed_ms=control.elapsed_ms,
                            error={
                                "code": "timed_out",
                                "message": "Deadline reached; executor may continue. No automatic retry.",
                            },
                        )

        Thread(target=worker, daemon=True, name=run_id).start()
        Thread(target=deadline, daemon=True, name=run_id + "_deadline").start()

    def close(self):
        with self._lock:
            self._closed = True
            for run_id, control in list(self._controls.items()):
                control.cancel()
                self._update(
                    run_id,
                    status="interrupted",
                    execution_state="unknown",
                    finished_at=now(),
                )
