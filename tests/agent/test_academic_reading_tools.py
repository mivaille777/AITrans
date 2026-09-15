from __future__ import annotations

from types import SimpleNamespace

from backend.agent_tools.base import AgentToolInvocationContext
from backend.agent_tools.reading import ReadingAgentTools, build_reading_tool_definitions


class _QuickActions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, **payload):
        self.calls.append(dict(payload))
        action = str(payload["action"])
        return SimpleNamespace(
            action=action,
            output_text=f"result:{action}",
            provider="fake",
            model="fake-model",
            request_id=int(payload.get("request_id", 0) or 0),
        )


def _context() -> AgentToolInvocationContext:
    return AgentToolInvocationContext(
        source_text="J(θ) = tracking error + control effort.",
        resource_title="Academic Paper",
        section_heading="Method",
        source_kind="knowledge_document",
        request_id=7,
    )


def test_academic_reading_tool_definitions_are_registered() -> None:
    definitions = build_reading_tool_definitions(
        ReadingAgentTools(quick_action_service=_QuickActions())
    )

    names = [definition.spec.name for definition in definitions]

    assert names == [
        "inspect_reading_context",
        "explain_selection",
        "summarize_selection",
        "analyze_section_role",
        "define_terms",
        "analyze_equation",
        "summarize_current_section",
    ]
    for name in ("define_terms", "analyze_equation", "summarize_current_section"):
        definition = next(item for item in definitions if item.spec.name == name)
        assert definition.spec.category == "reading"
        assert definition.spec.effect == "compute"
        assert definition.spec.requires_reading_context is True
        assert definition.spec.requires_confirmation is False


def test_academic_reading_tools_map_to_source_bound_actions() -> None:
    service = _QuickActions()
    definitions = build_reading_tool_definitions(
        ReadingAgentTools(quick_action_service=service)
    )
    by_name = {definition.spec.name: definition for definition in definitions}
    context = _context()

    expected = {
        "define_terms": "reading_define_terms",
        "analyze_equation": "reading_analyze_equation",
        "summarize_current_section": "reading_section_summarize",
    }
    for tool_name, action in expected.items():
        definition = by_name[tool_name]
        result = definition.executor(context, definition.args_model())
        normalized = definition.normalize_execution_result(result)
        assert normalized.output_text == f"result:{action}"
        assert normalized.data == {"action": action}

    assert [str(call["action"]) for call in service.calls] == list(expected.values())
    assert all(call["source_kind"] == "knowledge_document" for call in service.calls)
