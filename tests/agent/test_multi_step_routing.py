from __future__ import annotations

from backend.models.agent_tools import AgentPlan
from backend.services.agent_router_service import AgentSemanticRouterService
from backend.services.agent_tool_registry import AgentToolSpec


def _tool(name: str) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        title=name,
        description=name,
        category="test",
        effect="compute",
        requires_reading_context=True,
        requires_confirmation=False,
        input_schema={},
    )


TOOLS = tuple(
    _tool(name)
    for name in (
        "translate_selection",
        "explain_selection",
        "summarize_selection",
        "polish_selection",
    )
)


class NeverPlanner:
    provider_name = "never"
    model = "never"
    prompt_id = "never@test"

    def __init__(self) -> None:
        self.calls = 0

    def plan(self, **_kwargs) -> AgentPlan:
        self.calls += 1
        raise AssertionError("Explicit compound routing should not call the single-step LLM planner.")


def _route(message: str):
    planner = NeverPlanner()
    router = AgentSemanticRouterService(planner=planner)
    route = router.route(
        tools=TOOLS,
        user_message=message,
        source_text="Gaussian Process",
        translated_text="",
        resource_url="",
        resource_title="Paper",
        section_heading="Method",
        context_before="",
        context_after="",
        source_kind="pdf",
        history=(),
    )
    return route, planner


def test_chinese_explicit_compound_request_routes_to_complex_without_llm() -> None:
    route, planner = _route("先翻译，然后解释一下")

    assert route.kind == "complex"
    assert route.source == "semantic_router"
    assert route.intent == "complex"
    assert planner.calls == 0


def test_english_explicit_compound_request_routes_to_complex_without_llm() -> None:
    route, planner = _route("Translate this and then summarize it")

    assert route.kind == "complex"
    assert route.source == "semantic_router"
    assert planner.calls == 0
