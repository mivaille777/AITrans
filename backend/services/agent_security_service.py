"""Security policy for untrusted reading context and planner authority."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.ai.errors import AIResponseError
from backend.models.agent_tools import AgentPlan
from backend.services.agent_tool_registry import AgentToolSpec


_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instruction",
        re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|system|developer)\b", re.I | re.S),
    ),
    (
        "system_prompt_request",
        re.compile(r"\b(system prompt|developer message|hidden instruction|reveal.*prompt)\b", re.I | re.S),
    ),
    (
        "tool_override_request",
        re.compile(r"\b(call|invoke|execute|use)\b.{0,40}\btool\b", re.I | re.S),
    ),
)


@dataclass(frozen=True, slots=True)
class AgentSecurityInspection:
    flags: tuple[str, ...]

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)


class AgentSecurityService:
    """Keep document text as untrusted data and bound planner authority."""

    def inspect_untrusted_context(self, **fields: Any) -> AgentSecurityInspection:
        flags: list[str] = []
        for name, value in fields.items():
            text = str(value or "")
            if not text:
                continue
            for flag, pattern in _INJECTION_PATTERNS:
                if pattern.search(text):
                    marker = f"{name}:{flag}"
                    if marker not in flags:
                        flags.append(marker)
        return AgentSecurityInspection(flags=tuple(flags))

    def validate_plan(
        self,
        plan: AgentPlan,
        *,
        tools: tuple[AgentToolSpec, ...],
    ) -> AgentPlan:
        if plan.action != "tool":
            return plan

        spec = next((tool for tool in tools if tool.name == plan.tool_name), None)
        if spec is None:
            raise AIResponseError(
                f"Agent planner selected an unregistered tool: {plan.tool_name}."
            )

        try:
            sanitized = spec.validate_planner_arguments(plan.arguments)
        except ValueError as exc:
            raise AIResponseError(str(exc)) from exc

        if sanitized != plan.arguments:
            return plan.model_copy(update={"arguments": sanitized})
        return plan


__all__ = ["AgentSecurityInspection", "AgentSecurityService"]
