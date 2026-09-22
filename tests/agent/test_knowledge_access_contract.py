from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models.agent_tools import AgentRunRequest
from backend.models.knowledge_access import (
    KnowledgeAccessDecision,
    KnowledgeAccessPolicy,
    KnowledgeScopeStrategy,
    ResolvedKnowledgeScope,
)


def test_policy_defaults_to_auto_and_round_trips() -> None:
    request = AgentRunRequest(user_message="Explain this", source_text="Context")

    assert request.knowledge_access_policy is KnowledgeAccessPolicy.AUTO
    assert request.model_dump(mode="json")["knowledge_access_policy"] == "auto"


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [(True, KnowledgeAccessPolicy.ALWAYS), (False, KnowledgeAccessPolicy.NEVER)],
)
def test_legacy_boolean_toggle_is_accepted_as_compatibility_layer(
    legacy: bool,
    expected: KnowledgeAccessPolicy,
) -> None:
    request = AgentRunRequest(
        user_message="Search for evidence",
        source_text="Context",
        knowledge_enabled=legacy,
    )

    assert request.knowledge_access_policy is expected


def test_new_policy_wins_over_legacy_boolean() -> None:
    request = AgentRunRequest(
        user_message="Do not search",
        source_text="Context",
        knowledge_access_policy="never",
        knowledge_enabled=True,
    )

    assert request.knowledge_access_policy is KnowledgeAccessPolicy.NEVER


def test_invalid_policy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentRunRequest(
            user_message="Explain this",
            source_text="Context",
            knowledge_access_policy="sometimes",
        )


def test_decision_and_scope_contracts_are_serializable() -> None:
    decision = KnowledgeAccessDecision(
        mode="always",
        should_retrieve=True,
        reason_code="explicit_always",
        scope_strategy="attached_document",
        confidence=1.0,
        query="find the results",
    )
    scope = ResolvedKnowledgeScope(
        strategy=KnowledgeScopeStrategy.ATTACHED_DOCUMENT,
        document_ids=["doc-a", "doc-a"],
        workspace_id="workspace-x",
        research_source_ids=["source-a"],
        allow_global=False,
        reason="Reading document is preferred over an unrelated workspace.",
    )

    assert decision.model_dump(mode="json")["mode"] == "always"
    assert scope.document_ids == ("doc-a",)
    assert scope.model_dump(mode="json")["strategy"] == "attached_document"
