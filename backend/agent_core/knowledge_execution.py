from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class KnowledgeExecutionResult:
    executed: bool
    tool_name: str
    output: dict[str, Any]
    reason: str


class SupervisorKnowledgeExecutor:
    """Bridge supervisor decisions to knowledge tool execution.

    Keeps routing separate from execution so AgentRuntime remains the owner of
    lifecycle, tracing and failure handling.
    """

    def __init__(self, tool_executor: Callable[..., Any] | None = None) -> None:
        self.tool_executor = tool_executor

    def execute_if_needed(self, decision: Any, state: Any) -> KnowledgeExecutionResult:
        if not getattr(decision, "need_knowledge", False):
            return KnowledgeExecutionResult(
                executed=False,
                tool_name="",
                output={},
                reason="knowledge retrieval not required",
            )

        tool_name = str(getattr(decision, "tool_name", "") or "")
        if not tool_name or self.tool_executor is None:
            return KnowledgeExecutionResult(
                executed=False,
                tool_name=tool_name,
                output={},
                reason="knowledge tool unavailable",
            )

        result = self.tool_executor(
            tool_name,
            query=str(getattr(state, "user_input", "") or ""),
        )
        return KnowledgeExecutionResult(
            executed=True,
            tool_name=tool_name,
            output=result if isinstance(result, dict) else {"result": result},
            reason="knowledge tool executed by supervisor decision",
        )


__all__ = ["KnowledgeExecutionResult", "SupervisorKnowledgeExecutor"]
