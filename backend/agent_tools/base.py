from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

AgentToolEffect = Literal["read", "compute", "write"]
AgentToolRetryPolicy = Literal["safe", "never"]


class AgentToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentToolInvocationContext(AgentToolModel):
    source_text: str = Field(default="", max_length=20_000)
    translated_text: str = Field(default="", max_length=50_000)
    source_language: str = Field(default="auto", min_length=1, max_length=64)
    target_language: str = Field(default="zh-CN", min_length=1, max_length=64)
    resource_url: str = Field(default="", max_length=4096)
    resource_title: str = Field(default="", max_length=1024)
    section_heading: str = Field(default="", max_length=1024)
    context_before: str = Field(default="", max_length=4000)
    context_after: str = Field(default="", max_length=4000)
    source_kind: str = Field(default="desktop", max_length=128)
    style: str = Field(default="academic", min_length=1, max_length=64)
    ai_action: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", max_length=128)
    request_id: int = Field(default=0, ge=0)
    run_id: str = Field(default="", max_length=128)
    trace_id: str = Field(default="", max_length=128)
    ai_content: str = Field(default="", max_length=50_000)
    knowledge_item_id: str = Field(default="", max_length=128)
    knowledge_writeback_type: str = Field(default="", max_length=64)
    knowledge_writeback_operation: str = Field(default="", max_length=128)
    knowledge_relation_type: str = Field(default="", max_length=128)
    memory_preferences: list[dict[str, Any]] = Field(
        default_factory=list, max_length=32
    )

    def reading_payload(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "resource_url": self.resource_url,
            "resource_title": self.resource_title,
            "section_heading": self.section_heading,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "source_kind": self.source_kind,
        }


class EmptyToolArgs(AgentToolModel):
    pass


class EmptyToolResultData(AgentToolModel):
    pass


@dataclass(frozen=True, slots=True)
class AgentToolSpec:
    """Public tool metadata consumed by the planner and HTTP catalog."""

    name: str
    title: str
    description: str
    category: str
    effect: AgentToolEffect
    requires_reading_context: bool
    requires_confirmation: bool
    input_schema: dict[str, Any]
    timeout_seconds: float = 20.0
    parallel_safe: bool = False
    idempotent: bool = False
    tool_version: str = "1"

    def __post_init__(self) -> None:
        if self.effect not in {"read", "compute", "write"}:
            raise ValueError(f"Agent tool {self.name} must declare a valid effect")
        if self.timeout_seconds <= 0 or not self.tool_version:
            raise ValueError(f"Agent tool {self.name} has invalid execution metadata")
        if self.effect == "write" and self.parallel_safe:
            raise ValueError("write tools cannot be parallel_safe")

    def validate_planner_arguments(self, arguments: dict[str, Any]) -> dict[str, str]:
        raw = {str(key): value for key, value in dict(arguments or {}).items()}
        unknown = set(raw) - set(self.input_schema)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(
                "Agent planner attempted arguments outside its authority; "
                f"{names} not accepted by tool {self.name}."
            )

        sanitized: dict[str, str] = {}
        for key, value in raw.items():
            schema = self.input_schema.get(key, {})
            text = str(value or "").strip()
            if isinstance(schema, dict):
                max_length = int(schema.get("maxLength", 0) or 0)
                min_length = int(schema.get("minLength", 0) or 0)
                if max_length > 0 and len(text) > max_length:
                    raise ValueError(
                        f"Agent planner argument {key} exceeds the allowed length for tool {self.name}."
                    )
                if min_length > 0 and len(text) < min_length:
                    raise ValueError(
                        f"Agent planner argument {key} is too short for tool {self.name}."
                    )
            sanitized[key] = text
        return sanitized


@dataclass(frozen=True, slots=True)
class AgentToolExecutionResult:
    """Stable successful Tool result shared by runtime, trace, and HTTP layers."""

    tool_name: str
    output_text: str
    effect: AgentToolEffect
    provider: str = ""
    model: str = ""
    request_id: int = 0
    data: dict[str, Any] | None = None


AgentToolExecutor = Callable[
    [AgentToolInvocationContext, BaseModel],
    AgentToolExecutionResult,
]


@dataclass(frozen=True, slots=True)
class TypedAgentToolDefinition:
    spec: AgentToolSpec
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    executor: AgentToolExecutor
    retry_policy: AgentToolRetryPolicy = "safe"

    def __post_init__(self) -> None:
        if self.retry_policy not in {"safe", "never"}:
            raise ValueError("invalid tool retry policy")
        if self.spec.effect == "write" and self.retry_policy != "never":
            raise ValueError("write tools cannot be automatically retried")

    @property
    def allows_safe_retry(self) -> bool:
        return self.retry_policy == "safe"

    def parse_args(self, payload: dict[str, Any]) -> BaseModel:
        candidate = {
            key: payload[key] for key in self.args_model.model_fields if key in payload
        }
        try:
            return self.args_model.model_validate(candidate)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid arguments for agent tool {self.spec.name}: {exc}"
            ) from exc

    def normalize_result_data(self, data: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return self.result_model.model_validate(dict(data or {})).model_dump(
                exclude_none=True
            )
        except ValidationError as exc:
            raise ValueError(
                f"Agent tool {self.spec.name} returned invalid structured result data: {exc}"
            ) from exc

    def normalize_execution_result(
        self,
        result: AgentToolExecutionResult,
    ) -> AgentToolExecutionResult:
        """Validate one executor result against the Tool-owned public contract."""

        if not isinstance(result, AgentToolExecutionResult):
            raise TypeError(
                f"Agent tool {self.spec.name} returned an invalid execution result object."
            )
        if result.tool_name != self.spec.name:
            raise ValueError(
                f"Agent tool {self.spec.name} returned mismatched result for {result.tool_name}."
            )
        if result.effect != self.spec.effect:
            raise ValueError(
                f"Agent tool {self.spec.name} returned effect {result.effect!r}; "
                f"expected {self.spec.effect!r}."
            )
        try:
            request_id = int(result.request_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Agent tool {self.spec.name} returned an invalid request_id."
            ) from exc
        if request_id < 0:
            raise ValueError(
                f"Agent tool {self.spec.name} returned an invalid request_id."
            )

        return AgentToolExecutionResult(
            tool_name=self.spec.name,
            output_text=str(result.output_text or ""),
            effect=self.spec.effect,
            provider=str(result.provider or ""),
            model=str(result.model or ""),
            request_id=request_id,
            data=self.normalize_result_data(result.data),
        )


def _model_properties(model: type[BaseModel]) -> dict[str, Any]:
    properties = model.model_json_schema().get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {
        str(key): dict(value) if isinstance(value, dict) else value
        for key, value in properties.items()
    }


def typed_tool_definition(
    *,
    name: str,
    title: str,
    description: str,
    category: str,
    effect: AgentToolEffect,
    requires_reading_context: bool,
    requires_confirmation: bool,
    args_model: type[BaseModel],
    result_model: type[BaseModel],
    executor: AgentToolExecutor,
    planner_args_model: type[BaseModel] | None = None,
    retry_policy: AgentToolRetryPolicy = "safe",
    timeout_seconds: float = 20.0,
    parallel_safe: bool | None = None,
    idempotent: bool | None = None,
    tool_version: str = "1",
) -> TypedAgentToolDefinition:
    input_schema = _model_properties(planner_args_model or args_model)
    return TypedAgentToolDefinition(
        spec=AgentToolSpec(
            name=name,
            title=title,
            description=description,
            category=category,
            effect=effect,
            requires_reading_context=requires_reading_context,
            requires_confirmation=requires_confirmation,
            input_schema=input_schema,
            timeout_seconds=timeout_seconds,
            parallel_safe=(effect != "write" if parallel_safe is None else parallel_safe),
            idempotent=(effect != "write" if idempotent is None else idempotent),
            tool_version=tool_version,
        ),
        args_model=args_model,
        result_model=result_model,
        executor=executor,
        retry_policy=retry_policy,
    )


__all__ = [
    "AgentToolEffect",
    "AgentToolExecutionResult",
    "AgentToolInvocationContext",
    "AgentToolModel",
    "AgentToolRetryPolicy",
    "AgentToolSpec",
    "EmptyToolArgs",
    "EmptyToolResultData",
    "TypedAgentToolDefinition",
    "typed_tool_definition",
]
