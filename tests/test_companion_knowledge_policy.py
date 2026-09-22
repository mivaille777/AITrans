from __future__ import annotations

from backend.models.companion import CompanionChatRequest
from backend.models.companion_routing import CompanionQueryRoute
from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.services.companion_chat_service import CompanionChatService


def test_companion_chat_request_maps_legacy_boolean_only_without_policy() -> None:
    legacy = CompanionChatRequest(
        context_mode="general",
        session_id="legacy-session",
        user_message="Search my papers",
        knowledge_enabled=True,
    )
    explicit_auto = CompanionChatRequest(
        context_mode="general",
        session_id="auto-session",
        user_message="Hello",
        knowledge_access_policy="auto",
        knowledge_enabled=False,
    )

    assert legacy.knowledge_access_policy is KnowledgeAccessPolicy.ALWAYS
    assert explicit_auto.knowledge_access_policy is KnowledgeAccessPolicy.AUTO


def test_companion_auto_skips_sufficient_reading_context() -> None:
    prepared = CompanionChatService().prepare_execution(
        query="总结当前选中的这段话",
        knowledge_access_policy="auto",
        context_mode="reading",
        source_text="A bounded reading selection.",
    )

    assert prepared.knowledge_decision is not None
    assert prepared.knowledge_decision.should_retrieve is False
    assert prepared.knowledge_decision.reason_code == "current_context_sufficient"
    assert prepared.plan.route is CompanionQueryRoute.READING_CONTEXT
    assert prepared.plan.use_knowledge is False


def test_companion_always_searches_even_when_reading_context_is_present() -> None:
    prepared = CompanionChatService().prepare_execution(
        query="总结当前选中的这段话",
        knowledge_access_policy="always",
        context_mode="reading",
        source_text="A bounded reading selection.",
    )

    assert prepared.knowledge_decision is not None
    assert prepared.knowledge_decision.reason_code == "explicit_always"
    assert prepared.plan.route is CompanionQueryRoute.KNOWLEDGE_SEARCH
    assert prepared.plan.use_knowledge is True


def test_companion_never_blocks_explicit_knowledge_request() -> None:
    prepared = CompanionChatService().prepare_execution(
        query="在知识库里找支持这个结论的证据",
        knowledge_access_policy="never",
        context_mode="general",
    )

    assert prepared.knowledge_decision is not None
    assert prepared.knowledge_decision.reason_code == "explicit_never"
    assert prepared.plan.route is CompanionQueryRoute.GENERAL
    assert prepared.plan.use_knowledge is False
