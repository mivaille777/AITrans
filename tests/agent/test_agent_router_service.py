from __future__ import annotations

from types import SimpleNamespace

from backend.models.agent_tools import AgentPlan
from backend.services.agent_router_service import (
    AgentDeterministicRouterService,
    AgentSemanticRouterService,
)
from backend.services.agent_tool_registry import AgentToolSpec


def _tool(name: str) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        title=name,
        description=name,
        category="test",
        effect="write" if name == "save_research_note" else "compute",
        requires_reading_context=True,
        requires_confirmation=name == "save_research_note",
        input_schema=(
            {"target_language": {"type": "string", "maxLength": 64}}
            if name == "translate_selection"
            else {}
        ),
    )


TOOLS = tuple(
    _tool(name)
    for name in (
        "translate_selection",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "polish_selection",
        "save_research_note",
    )
)


def test_explicit_reading_commands_route_without_semantic_inference() -> None:
    router = AgentDeterministicRouterService()

    assert router.route(user_message="翻译一下", tools=TOOLS).tool_name == "translate_selection"
    assert router.route(user_message="解释一下", tools=TOOLS).tool_name == "explain_selection"
    assert router.route(user_message="总结一下", tools=TOOLS).tool_name == "summarize_selection"
    assert router.route(user_message="润色一下", tools=TOOLS).tool_name == "polish_selection"
    assert router.route(user_message="保存成笔记", tools=TOOLS).tool_name == "save_research_note"

    for command in ("翻译一下", "解释一下", "总结一下", "润色一下", "保存成笔记"):
        assert router.route(user_message=command, tools=TOOLS).source == "deterministic"


def test_explicit_translation_target_is_parsed_deterministically() -> None:
    router = AgentDeterministicRouterService()

    chinese = router.route(user_message="翻成英文", tools=TOOLS)
    english = router.route(user_message="translate this to Japanese", tools=TOOLS)

    assert chinese.tool_name == "translate_selection"
    assert chinese.arguments == {"target_language": "en"}
    assert english.arguments == {"target_language": "ja"}


def test_canvas_structure_inspection_routes_directly_without_planner() -> None:
    router = AgentDeterministicRouterService()
    route = router.route(
        user_message=(
            "List every explicit Canvas relation available in your current context. "
            "For each relation, give relation id, source card title, target card title, "
            "relation type, label, and origin. Do not infer missing relations."
        ),
        tools=TOOLS,
    )

    assert route.kind == "answer"
    assert route.source == "deterministic"
    assert route.intent == "answer"
    assert route.tool_name == ""


def test_canvas_factual_verification_stays_on_semantic_path() -> None:
    router = AgentDeterministicRouterService()
    route = router.route(
        user_message="Verify whether the Canvas relations are factual scientific evidence.",
        tools=TOOLS,
    )

    assert route.kind == "unresolved"
    assert route.source == "none"


def test_compound_requests_are_not_swallowed_by_fast_router() -> None:
    router = AgentDeterministicRouterService()

    compound = router.route(
        user_message="翻译完了之后帮我解释第三句话",
        tools=TOOLS,
    )
    question = router.route(
        user_message="为什么这里的翻译策略比直接调用模型更可靠？",
        tools=TOOLS,
    )

    assert compound.kind == "unresolved"
    assert compound.source == "none"
    assert question.kind == "unresolved"


def test_missing_registered_tool_keeps_route_unresolved() -> None:
    router = AgentDeterministicRouterService()

    route = router.route(
        user_message="翻译一下",
        tools=tuple(tool for tool in TOOLS if tool.name != "translate_selection"),
    )

    assert route.kind == "unresolved"
    assert route.tool_name == ""


class FakePlanner:
    provider_name = "fake-router"
    model = "fake-model"
    prompt_id = "agent.planner@test"

    def __init__(self, plan: AgentPlan) -> None:
        self.plan_result = plan
        self.calls = 0

    def plan(self, **_kwargs):
        self.calls += 1
        return self.plan_result

    def close(self) -> None:
        return None


def test_semantic_router_wraps_existing_single_step_planner() -> None:
    planner = FakePlanner(
        AgentPlan(
            action="tool",
            tool_name="explain_selection",
            user_visible_reason="Use reading evidence.",
        )
    )
    router = AgentSemanticRouterService(planner=planner)

    route = router.route(
        tools=TOOLS,
        user_message="Why does this argument matter?",
        source_text="Evidence",
        translated_text="",
        resource_url="",
        resource_title="Paper",
        section_heading="Method",
        context_before="",
        context_after="",
        source_kind="pdf",
    )

    assert planner.calls == 1
    assert route.kind == "tool"
    assert route.source == "semantic_router"
    assert route.tool_name == "explain_selection"
    assert router.provider_name == "fake-router"
