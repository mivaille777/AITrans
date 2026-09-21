from __future__ import annotations

import pytest

from backend.models.companion_routing import CompanionQueryRoute, GroundingPolicy
from backend.services.companion_query_router import CompanionQueryRouter


@pytest.mark.parametrize(
    ("query", "knowledge_enabled", "reading_attached", "document_ids", "expected"),
    [
        ("我是谁", True, False, (), CompanionQueryRoute.SYSTEM_IDENTITY),
        ("你能做什么", True, False, (), CompanionQueryRoute.SYSTEM_IDENTITY),
        ("你是什么模型", True, False, (), CompanionQueryRoute.SYSTEM_IDENTITY),
        ("资料库里有什么", True, False, (), CompanionQueryRoute.KNOWLEDGE_CATALOG),
        ("我导入了哪些论文", True, False, (), CompanionQueryRoute.KNOWLEDGE_CATALOG),
        ("总结这段文字", True, True, (), CompanionQueryRoute.READING_CONTEXT),
        (
            "Measurement 这篇论文的结论是什么",
            True,
            False,
            (),
            CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH,
        ),
        (
            "资料库里的 PID tuning 怎么做",
            True,
            False,
            (),
            CompanionQueryRoute.KNOWLEDGE_SEARCH,
        ),
        ("你好", False, False, (), CompanionQueryRoute.GENERAL),
    ],
)
def test_companion_query_router_is_deterministic(
    query: str,
    knowledge_enabled: bool,
    reading_attached: bool,
    document_ids: tuple[str, ...],
    expected: CompanionQueryRoute,
) -> None:
    router = CompanionQueryRouter()

    first = router.route(
        query,
        knowledge_enabled=knowledge_enabled,
        reading_attached=reading_attached,
        document_ids=document_ids,
    )
    second = router.route(
        query,
        knowledge_enabled=knowledge_enabled,
        reading_attached=reading_attached,
        document_ids=document_ids,
    )

    assert first == second
    assert first.route is expected


def test_router_maps_grounding_policy_by_capability() -> None:
    router = CompanionQueryRouter()

    identity = router.route("我是谁", knowledge_enabled=True)
    catalog = router.route("资料库里有什么", knowledge_enabled=True)
    search = router.route("资料库里的 PID tuning 怎么做", knowledge_enabled=True)

    assert identity.grounding_policy is GroundingPolicy.NONE
    assert identity.use_knowledge is False
    assert catalog.grounding_policy is GroundingPolicy.MANIFEST
    assert catalog.use_knowledge is False
    assert search.grounding_policy is GroundingPolicy.EVIDENCE
    assert search.use_knowledge is True


def test_selected_documents_produce_bounded_document_scope() -> None:
    plan = CompanionQueryRouter().route(
        "解释 PID tuning",
        knowledge_enabled=True,
        document_ids=(" doc-2 ", "doc-1", "doc-2", ""),
    )

    assert plan.route is CompanionQueryRoute.DOCUMENT_SCOPED_SEARCH
    assert plan.document_ids == ("doc-2", "doc-1")
    assert plan.reason == "selected_knowledge_documents"


def test_knowledge_off_never_selects_local_knowledge_for_general_query() -> None:
    plan = CompanionQueryRouter().route(
        "我的知识库如何描述 PID",
        knowledge_enabled=False,
    )

    assert plan.route is CompanionQueryRoute.GENERAL
    assert plan.use_knowledge is False
    assert plan.grounding_policy is GroundingPolicy.NONE
