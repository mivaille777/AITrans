from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend.models.agent_runtime import AgentRouteDecision
from backend.services.agent_planner_service import AgentPlannerService
from backend.services.agent_tool_registry import AgentToolSpec


_LANGUAGE_ALIASES = {
    "中文": "zh-CN",
    "汉语": "zh-CN",
    "简体中文": "zh-CN",
    "繁体中文": "zh-TW",
    "英文": "en",
    "英语": "en",
    "日文": "ja",
    "日语": "ja",
    "韩文": "ko",
    "韩语": "ko",
    "法文": "fr",
    "法语": "fr",
    "德文": "de",
    "德语": "de",
    "西班牙文": "es",
    "西班牙语": "es",
    "俄文": "ru",
    "俄语": "ru",
    "chinese": "zh-CN",
    "simplified chinese": "zh-CN",
    "traditional chinese": "zh-TW",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "russian": "ru",
}

_ZH_LANGUAGE_PATTERN = "|".join(
    sorted((re.escape(item) for item in _LANGUAGE_ALIASES if not item.isascii()), key=len, reverse=True)
)
_EN_LANGUAGE_PATTERN = "|".join(
    sorted((re.escape(item) for item in _LANGUAGE_ALIASES if item.isascii()), key=len, reverse=True)
)

_ZH_TRANSLATE_TARGET = re.compile(
    rf"^(?:请)?(?:帮我)?(?:把|将)?(?:这段(?:话|文字|内容)?|这句话|选中(?:的)?(?:内容|文字)|当前选区|它)?"
    rf"(?:翻译|翻|译)(?:一下)?(?:成|为)(?P<language>{_ZH_LANGUAGE_PATTERN})$"
)
_EN_TRANSLATE_TARGET = re.compile(
    rf"^(?:please\s+)?translate(?:\s+this|\s+the\s+selection|\s+selection)?"
    rf"(?:\s+into|\s+to)\s+(?P<language>{_EN_LANGUAGE_PATTERN})$",
    re.IGNORECASE,
)

_TRANSLATE_COMMANDS = frozenset(
    {
        "翻译一下",
        "帮我翻译一下",
        "请翻译一下",
        "翻译这段",
        "翻译这段话",
        "翻译这段文字",
        "翻译选中内容",
        "翻译选中的内容",
        "翻译当前选区",
        "translate this",
        "translate selection",
        "translate the selection",
    }
)
_EXPLAIN_COMMANDS = frozenset(
    {
        "解释一下",
        "帮我解释一下",
        "请解释一下",
        "解释这段",
        "解释这段话",
        "解释这段文字",
        "解释选中内容",
        "解释选中的内容",
        "explain this",
        "explain selection",
        "explain the selection",
    }
)
_SUMMARIZE_COMMANDS = frozenset(
    {
        "总结一下",
        "帮我总结一下",
        "请总结一下",
        "总结这段",
        "总结这段话",
        "总结选中内容",
        "概括一下",
        "概括这段",
        "summarize this",
        "summarize selection",
        "summarize the selection",
    }
)
_POLISH_COMMANDS = frozenset(
    {
        "润色一下",
        "帮我润色一下",
        "请润色一下",
        "润色这段",
        "润色这段文字",
        "润色选中内容",
        "polish this",
        "polish selection",
        "polish the selection",
    }
)
_SECTION_ROLE_COMMANDS = frozenset(
    {
        "分析这段的作用",
        "分析这段在本节中的作用",
        "分析这段在文章中的作用",
        "分析选中内容的作用",
        "analyze section role",
        "analyze the section role",
    }
)
_SAVE_NOTE_COMMANDS = frozenset(
    {
        "保存成笔记",
        "保存为笔记",
        "保存笔记",
        "记到笔记",
        "记入笔记",
        "把它保存成笔记",
        "把这段保存成笔记",
        "save as note",
        "save this as a note",
        "save this note",
    }
)
_SAVE_KNOWLEDGE_COMMANDS = frozenset(
    {
        "保存到知识库",
        "保存到知识卡片",
        "保存为知识卡片",
        "把结果保存到知识库",
        "把这个结果保存到知识库",
        "save to knowledge",
        "save to knowledge library",
        "save this result to knowledge",
        "save this agent result to knowledge",
    }
)

_COMPOUND_CONNECTORS = (
    "然后",
    "之后",
    "再",
    "并且",
    "并",
    "同时",
    "接着",
    "and then",
    " then ",
    " and ",
    "after that",
)
_COMPOUND_ACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("translate", re.compile(r"(翻译|翻成|译成|\btranslate\b)", re.I)),
    ("explain", re.compile(r"(解释|\bexplain\b)", re.I)),
    ("summarize", re.compile(r"(总结|概括|\bsummarize\b)", re.I)),
    ("polish", re.compile(r"(润色|\bpolish\b)", re.I)),
    ("section_role", re.compile(r"(分析.{0,12}(作用|角色)|section\s+role)", re.I)),
    ("save_note", re.compile(r"(保存.{0,8}笔记|记到笔记|记入笔记|save.{0,10}note)", re.I)),
    ("save_knowledge", re.compile(r"(保存.{0,10}知识库|保存.{0,10}知识卡片|save.{0,16}knowledge)", re.I)),
)


def _normalize_command(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[。.!！?？]+$", "", text).strip()
    return text.casefold()


def _tool_names(tools: tuple[AgentToolSpec, ...]) -> frozenset[str]:
    return frozenset(tool.name for tool in tools)


def _looks_like_compound_request(value: object) -> bool:
    """Recognize explicit multi-action requests supported by the current tool set."""

    command = _normalize_command(value)
    if not command or not any(connector in command for connector in _COMPOUND_CONNECTORS):
        return False
    actions = {
        name
        for name, pattern in _COMPOUND_ACTION_PATTERNS
        if pattern.search(command)
    }
    return len(actions) >= 2


class AgentDeterministicRouterService:
    """Route explicit product commands without an LLM call.

    Matching is deliberately full-command only. Requests that contain an
    explicit action plus additional work remain unresolved so the semantic
    router can interpret the compound request instead of silently dropping it.
    """

    @staticmethod
    def _tool_route(
        *,
        tool_name: str,
        available_tools: frozenset[str],
        reason: str,
        arguments: dict[str, str] | None = None,
    ) -> AgentRouteDecision:
        if tool_name not in available_tools:
            return AgentRouteDecision()
        return AgentRouteDecision(
            kind="tool",
            source="deterministic",
            intent=tool_name,
            tool_name=tool_name,
            user_visible_reason=reason,
            arguments=dict(arguments or {}),
        )

    def route(
        self,
        *,
        user_message: str,
        tools: tuple[AgentToolSpec, ...],
        **_: Any,
    ) -> AgentRouteDecision:
        command = _normalize_command(user_message)
        available = _tool_names(tools)
        if not command:
            return AgentRouteDecision()

        target_match = _ZH_TRANSLATE_TARGET.fullmatch(command)
        if target_match is None:
            target_match = _EN_TRANSLATE_TARGET.fullmatch(command)
        if target_match is not None:
            language = target_match.group("language").casefold()
            return self._tool_route(
                tool_name="translate_selection",
                available_tools=available,
                reason="Translate the current reading selection.",
                arguments={"target_language": _LANGUAGE_ALIASES[language]},
            )

        if command in _TRANSLATE_COMMANDS:
            return self._tool_route(
                tool_name="translate_selection",
                available_tools=available,
                reason="Translate the current reading selection.",
            )
        if command in _EXPLAIN_COMMANDS:
            return self._tool_route(
                tool_name="explain_selection",
                available_tools=available,
                reason="Explain the current reading selection.",
            )
        if command in _SUMMARIZE_COMMANDS:
            return self._tool_route(
                tool_name="summarize_selection",
                available_tools=available,
                reason="Summarize the current reading selection.",
            )
        if command in _POLISH_COMMANDS:
            return self._tool_route(
                tool_name="polish_selection",
                available_tools=available,
                reason="Polish the current reading selection.",
            )
        if command in _SECTION_ROLE_COMMANDS:
            return self._tool_route(
                tool_name="analyze_section_role",
                available_tools=available,
                reason="Analyze the role of the current reading selection.",
            )
        if command in _SAVE_NOTE_COMMANDS:
            return self._tool_route(
                tool_name="save_research_note",
                available_tools=available,
                reason="Save the current reading selection to Research Notes.",
            )
        if command in _SAVE_KNOWLEDGE_COMMANDS:
            return self._tool_route(
                tool_name="save_knowledge_card",
                available_tools=available,
                reason="Save the confirmed Agent result to the canonical Knowledge Library.",
            )
        return AgentRouteDecision()


class AgentSemanticRouterService:
    """Semantic router with a conservative Stage 10.6 complex-task boundary."""

    def __init__(
        self,
        planner: AgentPlannerService | Any | None = None,
        *,
        text_service: Any | None = None,
    ) -> None:
        self._planner = planner or AgentPlannerService(text_service=text_service)

    @property
    def provider_name(self) -> str:
        return str(getattr(self._planner, "provider_name", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self._planner, "model", "") or "")

    @property
    def prompt_id(self) -> str:
        return str(getattr(self._planner, "prompt_id", "") or "")

    def route(self, *, tools: tuple[AgentToolSpec, ...], **payload: Any) -> AgentRouteDecision:
        if _looks_like_compound_request(payload.get("user_message", "")):
            return AgentRouteDecision(
                kind="complex",
                source="semantic_router",
                intent="complex",
                user_visible_reason="This request combines multiple reading actions.",
            )

        plan = self._planner.plan(tools=tools, **payload)
        if plan.action == "tool":
            return AgentRouteDecision(
                kind="tool",
                source="semantic_router",
                intent=plan.tool_name,
                tool_name=plan.tool_name,
                user_visible_reason=plan.user_visible_reason,
                arguments=dict(plan.arguments),
            )
        return AgentRouteDecision(
            kind="answer",
            source="semantic_router",
            intent="answer",
            user_visible_reason=plan.user_visible_reason,
        )

    def close(self) -> None:
        close = getattr(self._planner, "close", None)
        if callable(close):
            close()


__all__ = [
    "AgentDeterministicRouterService",
    "AgentSemanticRouterService",
]
