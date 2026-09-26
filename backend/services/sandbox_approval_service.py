"""Thread-safe, bounded service for user decisions and single-use grants."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from backend.models.sandbox_approval import (
    PermissionGrant,
    SandboxApprovalChange,
    SandboxApprovalRequest,
)
from backend.models.sandbox_permissions import PermissionDecision, PermissionRequest

_DEFAULT_TTL_SECONDS = 300
_MAX_TTL_SECONDS = 3600
_MAX_APPROVALS = 1000


class SandboxApprovalError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SandboxApprovalService:
    """Keep approval state in process; restart or expiry invalidates every grant."""

    def __init__(
        self,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_approvals: int = _MAX_APPROVALS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 < ttl_seconds <= _MAX_TTL_SECONDS:
            raise ValueError("Approval TTL must be between 1 and 3600 seconds.")
        if max_approvals < 1:
            raise ValueError("max_approvals must be positive.")
        self.ttl_seconds = ttl_seconds
        self.max_approvals = max_approvals
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._approvals: OrderedDict[str, SandboxApprovalRequest] = OrderedDict()
        self._grants: dict[str, PermissionGrant] = {}
        self._grant_ids_by_approval: dict[str, str] = {}

    def create_approval(
        self,
        request: PermissionRequest,
        decision: PermissionDecision,
        *,
        requested_changes: tuple[SandboxApprovalChange, ...] = (),
    ) -> SandboxApprovalRequest:
        if decision.decision != "approval_required":
            raise SandboxApprovalError(
                "approval_not_required",
                "Only policy decisions requiring approval can create an approval request.",
                status_code=400,
            )
        if not request.run_id.strip() or not request.tool_call_id.strip():
            raise SandboxApprovalError(
                "approval_binding_required",
                "An approval must be bound to a run and tool call.",
                status_code=400,
            )
        if decision.granted_scope.get("action") != request.action:
            raise SandboxApprovalError(
                "approval_scope_mismatch",
                "The requested scope does not match the policy decision.",
                status_code=400,
            )
        if decision.granted_scope.get("target") != (request.target or None):
            raise SandboxApprovalError(
                "approval_scope_mismatch",
                "The requested target does not match the policy decision.",
                status_code=400,
            )

        now = self._now()
        approval = SandboxApprovalRequest(
            approval_id=f"apr_{uuid4().hex}",
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            permission_action=request.action,
            target=request.target,
            reason=request.reason,
            requested_scope=deepcopy(decision.granted_scope),
            requested_changes=requested_changes,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        with self._lock:
            self._make_room()
            self._approvals[approval.approval_id] = approval
        return approval.model_copy(deep=True)

    def list_pending(self) -> list[SandboxApprovalRequest]:
        with self._lock:
            self._expire_due()
            return [
                approval.model_copy(deep=True)
                for approval in self._approvals.values()
                if approval.status == "pending"
            ]

    def get(self, approval_id: str) -> SandboxApprovalRequest:
        with self._lock:
            approval = self._expire_if_due(self._get(approval_id))
            return approval.model_copy(deep=True)

    def approve(self, approval_id: str) -> SandboxApprovalRequest:
        with self._lock:
            approval = self._get(approval_id)
            approval = self._require_pending(approval)
            grant = PermissionGrant(
                grant_id=f"grt_{uuid4().hex}",
                approval_id=approval.approval_id,
                action=approval.permission_action,
                scope=deepcopy(approval.requested_scope),
                run_id=approval.run_id,
                tool_call_id=approval.tool_call_id,
                expires_at=approval.expires_at,
            )
            approved = approval.model_copy(update={"status": "approved"})
            self._approvals[approval_id] = approved
            self._grants[grant.grant_id] = grant
            self._grant_ids_by_approval[approval_id] = grant.grant_id
            return approved.model_copy(deep=True)

    def deny(self, approval_id: str) -> SandboxApprovalRequest:
        with self._lock:
            approval = self._get(approval_id)
            approval = self._require_pending(approval)
            denied = approval.model_copy(update={"status": "denied"})
            self._approvals[approval_id] = denied
            return denied.model_copy(deep=True)

    def consume_grant(
        self,
        approval_id: str,
        *,
        action: str,
        scope: Mapping[str, str | bool | int | None],
        run_id: str,
        tool_call_id: str,
    ) -> PermissionGrant:
        with self._lock:
            approval = self._expire_if_due(self._get(approval_id))
            if approval.status == "expired":
                raise SandboxApprovalError(
                    "approval_expired",
                    "Sandbox approval has expired.",
                    status_code=409,
                )
            if approval.status == "consumed":
                raise SandboxApprovalError(
                    "approval_grant_replayed",
                    "This approval grant has already been consumed.",
                    status_code=409,
                )
            if approval.status != "approved":
                raise SandboxApprovalError(
                    "approval_not_approved",
                    "This approval does not have an active grant.",
                    status_code=403,
                )

            grant_id = self._grant_ids_by_approval.get(approval_id, "")
            grant = self._grants.get(grant_id)
            if grant is None:
                raise SandboxApprovalError(
                    "approval_grant_unavailable",
                    "This approval grant is no longer available.",
                    status_code=403,
                )
            if (
                action != grant.action
                or run_id != grant.run_id
                or tool_call_id != grant.tool_call_id
                or dict(scope) != grant.scope
            ):
                raise SandboxApprovalError(
                    "approval_grant_scope_mismatch",
                    "The approval grant does not match this action, scope, run, and tool call.",
                    status_code=403,
                )

            consumed = approval.model_copy(update={"status": "consumed"})
            self._approvals[approval_id] = consumed
            self._grants.pop(grant_id, None)
            self._grant_ids_by_approval.pop(approval_id, None)
            return grant.model_copy(deep=True)

    def close(self) -> None:
        """Clear ephemeral approvals and grants so shutdown cannot preserve authority."""

        with self._lock:
            self._approvals.clear()
            self._grants.clear()
            self._grant_ids_by_approval.clear()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Approval clock must return a timezone-aware datetime.")
        return value.astimezone(UTC)

    def _get(self, approval_id: str) -> SandboxApprovalRequest:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise SandboxApprovalError(
                "approval_not_found", "Sandbox approval was not found.", status_code=404
            )
        return approval

    def _require_pending(
        self,
        approval: SandboxApprovalRequest,
    ) -> SandboxApprovalRequest:
        approval = self._expire_if_due(approval)
        if approval.status == "expired":
            raise SandboxApprovalError(
                "approval_expired", "Sandbox approval has expired.", status_code=409
            )
        if approval.status != "pending":
            raise SandboxApprovalError(
                "approval_already_decided",
                "Sandbox approval is no longer pending.",
                status_code=409,
            )
        return approval

    def _expire_due(self) -> None:
        now = self._now()
        for approval_id, approval in tuple(self._approvals.items()):
            if (
                approval.status in {"pending", "approved"}
                and approval.expires_at <= now
            ):
                self._mark_expired(approval_id, approval)

    def _expire_if_due(
        self,
        approval: SandboxApprovalRequest,
    ) -> SandboxApprovalRequest:
        if (
            approval.status in {"pending", "approved"}
            and approval.expires_at <= self._now()
        ):
            self._mark_expired(approval.approval_id, approval)
            return self._approvals[approval.approval_id]
        return approval

    def _mark_expired(
        self,
        approval_id: str,
        approval: SandboxApprovalRequest,
    ) -> None:
        self._approvals[approval_id] = approval.model_copy(update={"status": "expired"})
        grant_id = self._grant_ids_by_approval.pop(approval_id, "")
        if grant_id:
            self._grants.pop(grant_id, None)

    def _make_room(self) -> None:
        self._expire_due()
        if len(self._approvals) < self.max_approvals:
            return
        for approval_id, approval in tuple(self._approvals.items()):
            if approval.status in {"denied", "expired", "consumed"}:
                self._approvals.pop(approval_id)
                if len(self._approvals) < self.max_approvals:
                    return
        raise SandboxApprovalError(
            "approval_capacity_reached",
            "Sandbox approval capacity is temporarily full.",
            status_code=503,
        )


__all__ = ["SandboxApprovalError", "SandboxApprovalService"]
