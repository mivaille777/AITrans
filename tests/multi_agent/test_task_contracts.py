from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from backend.agent_core.orchestration.ports import (
    ArtifactPort,
    BudgetPort,
    EvidencePort,
    MemoryPort,
    ToolRuntimePort,
)
from backend.agent_core.orchestration.roles import RoleRegistry
from backend.models.agent_artifacts import (
    ArtifactKind,
    DocumentAnalysisArtifact,
)
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec
from backend.models.agent_tools import AgentRunRequest


def _scope() -> ScopeContext:
    return ScopeContext.issue(
        profile_id="profile-1",
        workspace_id="workspace-a",
        scope_revision="rev-7",
        allowed_document_ids=["paper-b", "paper-a", "paper-a"],
        allowed_note_ids=["note-1"],
        memory_policy_revision="memory-2",
    )


def test_scope_context_is_server_shaped_and_deterministic() -> None:
    first = _scope()
    second = ScopeContext.issue(
        profile_id="profile-1",
        workspace_id="workspace-a",
        scope_revision="rev-7",
        allowed_document_ids=["paper-a", "paper-b"],
        allowed_note_ids=["note-1"],
        memory_policy_revision="memory-2",
    )

    assert first == second
    assert first.allowed_document_ids == ["paper-a", "paper-b"]
    assert first.scope_ref.startswith("scope:")


def test_task_contract_requires_required_flag_and_rejects_authority_fields() -> None:
    scope = _scope()
    base = {
        "task_id": "doc-a",
        "role": "document",
        "objective": "Analyze paper A.",
        "expected_output_kind": "document_analysis",
        "scope_ref": scope.scope_ref,
    }

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(base)

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(
            {
                **base,
                "required": True,
                "profile_id": "attacker-profile",
                "workspace_id": "workspace-b",
                "model": "unapproved-model",
            }
        )


def test_artifact_contract_rejects_non_serializable_python_objects() -> None:
    scope = _scope()
    with pytest.raises((ValidationError, ValueError, TypeError)):
        DocumentAnalysisArtifact(
            artifact_id="analysis-a",
            producer_task_id="doc-a",
            scope_ref=scope.scope_ref,
            document_id="paper-a",
            content={"connection": object()},
        )


def test_legacy_agent_request_still_parses() -> None:
    request = AgentRunRequest(
        session_id="legacy-session",
        user_message="Summarize this selection.",
        source_text="A bounded paragraph.",
        source_language="en",
        target_language="zh-CN",
    )

    assert request.session_id == "legacy-session"
    assert request.context_mode == "reading"
    assert request.workspace_id == ""


def test_role_registry_keeps_legacy_names_as_adapters() -> None:
    registry = RoleRegistry()

    assert registry.adapt_legacy("reading").role == TaskRole.DOCUMENT
    assert registry.adapt_legacy("research").role == TaskRole.RESEARCH
    translation = registry.adapt_legacy("translation")
    assert translation.role == TaskRole.WRITER
    assert translation.capability_only is True


@dataclass
class _Memory:
    def load_snapshot(self, *, profile_id, scope):
        return {"available": False, "profile_id": profile_id, "scope": scope.scope_ref}


@dataclass
class _Evidence:
    def retrieve(self, *, query, scope, limit):
        return ()


@dataclass
class _Tools:
    def execute(self, *, task, tool_name, arguments, scope):
        return {"tool": tool_name, "scope": scope.scope_ref}


@dataclass
class _Artifacts:
    def put(self, artifact):
        return artifact

    def get(self, artifact_id, version, *, include_revoked=False):
        return None

    def list_versions(self, artifact_id, *, include_revoked=False):
        return ()

    def revoke(self, artifact_id, version, *, reason):
        return False

    def migrate(self, target_version=None):
        return 1


@dataclass
class _Budget:
    def reserve(self, *, budget_ref, task_id, resource, amount):
        return True

    def record(self, *, budget_ref, task_id, usage):
        return None


def test_ports_accept_pure_test_doubles() -> None:
    assert isinstance(_Memory(), MemoryPort)
    assert isinstance(_Evidence(), EvidencePort)
    assert isinstance(_Tools(), ToolRuntimePort)
    assert isinstance(_Artifacts(), ArtifactPort)
    assert isinstance(_Budget(), BudgetPort)
