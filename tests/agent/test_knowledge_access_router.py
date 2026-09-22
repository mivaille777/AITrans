from __future__ import annotations

from types import SimpleNamespace

from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.state import AgentState
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.knowledge_access import KnowledgeAccessPolicy
from backend.services.knowledge_access_router import KnowledgeAccessRouter


def test_greeting_does_not_need_knowledge() -> None:
    router = KnowledgeAccessRouter()

    decision = router.route(user_message="你好", context_mode="general")

    assert decision.should_retrieve is False
    assert decision.reason_code == "current_context_sufficient"


def test_rewrite_and_translation_stay_on_direct_context_path() -> None:
    router = KnowledgeAccessRouter()

    rewrite = router.route(
        user_message="把这句话改写得更正式一些",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )
    translation = router.route(
        user_message="Translate this paragraph into Chinese",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )

    assert rewrite.should_retrieve is False
    assert translation.should_retrieve is False
    assert rewrite.reason_code == "current_context_sufficient"


def test_current_passage_summary_skips_retrieval_when_context_is_sufficient() -> None:
    decision = KnowledgeAccessRouter().route(
        user_message="总结当前选中的这段话",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )

    assert decision.should_retrieve is False
    assert decision.reason_code == "current_context_sufficient"


def test_current_paper_cross_section_question_retrieves_attached_document() -> None:
    decision = KnowledgeAccessRouter().route(
        user_message="根据当前论文的完整实验结果判断作者的结论是否成立",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )

    assert decision.should_retrieve is True
    assert decision.reason_code == "current_context_insufficient"
    assert decision.scope_strategy.value == "attached_document"


def test_related_paper_search_and_explicit_knowledge_request_retrieve() -> None:
    router = KnowledgeAccessRouter()

    related = router.route(
        user_message="找相关工作和相关论文",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )
    explicit = router.route(
        user_message="在知识库里找支持这个结论的证据",
        context_mode="general",
        knowledge_available=True,
    )

    assert related.should_retrieve is True
    assert related.reason_code == "knowledge_request"
    assert explicit.should_retrieve is True
    assert explicit.reason_code == "knowledge_request"


def test_cross_document_comparison_uses_cross_document_reason_code() -> None:
    decision = KnowledgeAccessRouter().route(
        user_message="比较跨文档中两种方法的差异",
        context_mode="research",
        workspace_available=True,
    )

    assert decision.should_retrieve is True
    assert decision.reason_code == "cross_document_request"


def test_policy_modes_override_automatic_routing() -> None:
    router = KnowledgeAccessRouter()

    never = router.route(
        user_message="在知识库里搜索这篇论文",
        policy=KnowledgeAccessPolicy.NEVER,
        context_mode="reading",
        attached_document="doc-A",
    )
    always = router.route(
        user_message="你好",
        policy=KnowledgeAccessPolicy.ALWAYS,
        context_mode="reading",
        attached_document="doc-A",
    )

    assert never.should_retrieve is False
    assert never.reason_code == "explicit_never"
    assert always.should_retrieve is True
    assert always.reason_code == "explicit_always"


def test_unresolved_request_uses_compact_semantic_fallback() -> None:
    calls: list[dict] = []

    def semantic(**payload):
        calls.append(payload)
        return {
            "should_retrieve": True,
            "reason_code": "semantic_router_required",
            "scope_strategy": "attached_document",
            "confidence": 0.86,
            "query": payload["user_message"],
        }

    router = KnowledgeAccessRouter(semantic_router=semantic)
    decision = router.route(
        user_message="这个方法和另一种方法相比有什么隐含差异？",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
        explicit_scope_count=1,
        workspace_available=True,
        context_summary="Paper A · Method",
    )

    assert decision.should_retrieve is True
    assert decision.reason_code == "semantic_router_required"
    assert router.semantic_calls == 1
    assert set(calls[0]) == {
        "user_message",
        "context_mode",
        "reading_context_available",
        "attached_document",
        "explicit_scope_count",
        "workspace_available",
        "knowledge_available",
        "context_summary",
    }
    assert "full_document_text" not in calls[0]


def test_semantic_router_failure_is_conservative_and_does_not_fail_run() -> None:
    def failing_semantic(**_payload):
        raise TimeoutError("semantic router timed out")

    router = KnowledgeAccessRouter(semantic_router=failing_semantic)
    reading = router.route(
        user_message="请判断这个方法是否可靠",
        context_mode="reading",
        reading_context_available=True,
        attached_document="doc-A",
    )
    general = router.route(
        user_message="请判断这个方法是否可靠",
        context_mode="general",
        reading_context_available=False,
    )

    assert reading.should_retrieve is True
    assert reading.reason_code == "document_grounding_required"
    assert general.should_retrieve is False
    assert general.reason_code == "current_context_sufficient"


class _RouteService:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self._registry = SimpleNamespace(
            list_tools=lambda: (
                SimpleNamespace(name="search_knowledge_base"),
                SimpleNamespace(name="explain_selection"),
            )
        )

    def resolve_route(self, **payload):
        self.payloads.append(dict(payload))
        return AgentRouteDecision(
            kind="answer",
            source="deterministic",
            intent="answer",
        ), {}


def test_runtime_never_blocks_knowledge_tools() -> None:
    service = _RouteService()
    adapter = ProductAgentRuntimeAdapter(service)
    state = AgentState(
        user_input="在知识库里搜索这篇论文",
        browser_context={"context_mode": "general", "knowledge_access_policy": "never"},
    )

    adapter.resolve_route(state)

    assert service.payloads[0]["disabled_tools"] == ["search_knowledge_base"]
    assert service.payloads[0]["enabled_tools"] == ["explain_selection"]
    assert state.browser_context["knowledge_decision"]["reason_code"] == "explicit_never"


def test_runtime_always_forces_initial_knowledge_retrieval() -> None:
    service = _RouteService()
    adapter = ProductAgentRuntimeAdapter(service)
    state = AgentState(
        user_input="你好",
        browser_context={"context_mode": "general", "knowledge_access_policy": "always"},
    )

    route, _metadata = adapter.resolve_route(state)

    assert route.tool_name == "search_knowledge_base"
    assert route.arguments == {"query": "你好"}
