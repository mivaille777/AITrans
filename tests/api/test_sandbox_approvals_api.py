from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.dependencies import get_sandbox_approval_service
from backend.main import create_app
from backend.models.sandbox_permissions import ExecutionPolicy, PermissionRequest
from backend.sandbox.permissions import PermissionPolicyEngine
from backend.services.sandbox_approval_service import SandboxApprovalService


def test_pending_approval_api_hides_grant_and_accepts_user_decision() -> None:
    service = SandboxApprovalService()
    request = PermissionRequest(
        action="filesystem.apply_host",
        target="src/app.py",
        reason="Apply the reviewed change.",
        run_id="run-api",
        tool_call_id="call-api",
    )
    decision = PermissionPolicyEngine().evaluate(
        request,
        ExecutionPolicy(profile="workspace_write", workspace_id="workspace-api"),
    )
    approval = service.create_approval(request, decision)

    app = create_app()
    app.dependency_overrides[get_sandbox_approval_service] = lambda: service
    client = TestClient(app)

    pending = client.get("/api/sandbox/approvals/pending")
    approved = client.post(f"/api/sandbox/approvals/{approval.approval_id}/approve")

    assert pending.status_code == 200
    assert pending.json()[0]["approval_id"] == approval.approval_id
    assert pending.json()[0]["status"] == "pending"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert "grant_id" not in approved.json()
    assert client.get("/api/sandbox/approvals/pending").json() == []
