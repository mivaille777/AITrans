from __future__ import annotations

from backend.models.companion_routing import CompanionQueryRoute, GroundingPolicy
from backend.services.companion_chat_service import CompanionChatService


class RetrievalProbe:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError("probe")


def test_prepare_execution_skips_retrieval_for_identity_route() -> None:
    retrieval = RetrievalProbe()
    service = CompanionChatService(retrieval_service=retrieval)

    prepared = service.prepare_execution(
        query="我是谁",
        knowledge_enabled=True,
        context_mode="general",
    )

    assert prepared.plan.route is CompanionQueryRoute.SYSTEM_IDENTITY
    assert prepared.plan.grounding_policy is GroundingPolicy.NONE
    assert prepared.plan.use_knowledge is False
    assert prepared.tool_name == ""
    assert retrieval.calls == 0


def test_prepare_execution_uses_evidence_contract_for_knowledge_search() -> None:
    retrieval = RetrievalProbe()
    service = CompanionChatService(retrieval_service=retrieval)

    prepared = service.prepare_execution(
        query="资料库里的 PID tuning 怎么做",
        knowledge_enabled=True,
        context_mode="general",
    )

    assert prepared.plan.route is CompanionQueryRoute.KNOWLEDGE_SEARCH
    assert prepared.plan.grounding_policy is GroundingPolicy.EVIDENCE
    assert prepared.plan.use_knowledge is True
    assert prepared.tool_name == "search_knowledge_base"
    assert retrieval.calls >= 1


def test_identity_route_does_not_initialize_optional_knowledge_services() -> None:
    calls = {
        "reading": 0,
        "retrieval": 0,
        "planner": 0,
        "library": 0,
    }

    def fail(name: str):
        def factory():
            calls[name] += 1
            raise AssertionError(f"{name} factory must not run for identity")

        return factory

    service = CompanionChatService(
        reading_resolver_factory=fail("reading"),
        retrieval_service_factory=fail("retrieval"),
        query_planner_factory=fail("planner"),
        knowledge_library_service_factory=fail("library"),
    )

    prepared = service.prepare_execution(
        query="你是谁？",
        knowledge_enabled=False,
        context_mode="general",
    )

    assert prepared.plan.route is CompanionQueryRoute.SYSTEM_IDENTITY
    assert prepared.direct_output_text
    assert "AITrans" in prepared.direct_output_text
    assert calls == {
        "reading": 0,
        "retrieval": 0,
        "planner": 0,
        "library": 0,
    }
