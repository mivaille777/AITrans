class AgentRuntimeError(Exception):
    """Base exception for agent runtime failures with trace-safe metadata."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "runtime",
        fallback_reason: str = "no_safe_fallback",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.fallback_reason = fallback_reason


class AgentToolError(AgentRuntimeError):
    """Raised when an agent tool execution fails."""


class AgentCancelledError(AgentRuntimeError):
    """Raised when cooperative Agent cancellation is observed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="cancellation", fallback_reason="user_cancelled")


class AgentBudgetExceededError(AgentRuntimeError):
    """Raised when the total Agent execution budget is exhausted."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            stage="execution_budget",
            fallback_reason="execution_budget_exhausted",
        )


class AgentToolTimeoutError(AgentToolError):
    """Raised when a safe read/compute tool exceeds its execution timeout."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            stage="tool",
            fallback_reason="tool_timeout_after_safe_retries",
        )


class AgentDecisionTimeoutError(AgentRuntimeError):
    """Raised when one side-effect-free ReAct decision exceeds its time bound."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            stage="react_decision",
            fallback_reason="react_decision_timeout",
        )
