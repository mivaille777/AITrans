"""Native Chat Completions tools shared by the existing provider clients."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionError,
    AIError,
    AIRateLimitError,
    AIResponseError,
    AITimeoutError,
)
from app.ai.runtime_status import track_llm_request


@dataclass(frozen=True, slots=True)
class ToolCompletion:
    message: dict[str, Any]

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self.message.get("tool_calls", [])

    @property
    def content(self) -> str:
        return self.message.get("content") or ""


def _completion(message: dict[str, Any], finish_reason: str | None) -> ToolCompletion:
    if finish_reason not in {"stop", "tool_calls"}:
        raise AIResponseError(f"Native tool response did not finish: {finish_reason}.")
    calls = message.get("tool_calls", [])
    if len(calls) > 16:
        raise AIResponseError("Native tool response contains too many calls.")
    identifiers: set[str] = set()
    for call in calls:
        function = call.get("function", {})
        identifier = call.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
            or call.get("type") != "function"
            or not isinstance(function.get("name"), str)
            or not function["name"]
            or not isinstance(function.get("arguments"), str)
            or len(function["arguments"]) > 16_000
        ):
            raise AIResponseError("Native tool response contains an invalid call.")
        identifiers.add(identifier)
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise AIResponseError("Native tool response contains invalid content.")
    if not calls and not str(content or "").strip():
        raise AIResponseError("Native tool response is empty.")
    if finish_reason == "tool_calls" and not calls:
        raise AIResponseError("Native tool response is missing its calls.")
    return ToolCompletion(message)


class NativeToolCallingClient:
    """Internal tool API; ordinary complete()/stream() contracts are unchanged."""

    def _tool_request(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        if not messages or tool_choice not in {"auto", "required", "none"}:
            raise AIConfigurationError("Invalid native tool request.")
        if tool_choice == "required" and not tools:
            raise AIConfigurationError("Required tool choice needs available tools.")
        request = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            request.update(tools=tools, tool_choice=tool_choice)
        thinking = bool(getattr(self, "thinking_enabled", False))
        if hasattr(self, "thinking_enabled"):
            # Required tool choice is unsupported in DeepSeek thinking mode.
            if thinking and tool_choice == "required":
                raise AIConfigurationError("Required tools need non-thinking mode.")
            request["extra_body"] = {
                "thinking": {"type": "enabled" if thinking else "disabled"}
            }
        if not thinking:
            request["temperature"] = self._validate_temperature(temperature)
        tokens = self._validate_max_tokens(max_tokens)
        if tokens is not None:
            request["max_tokens"] = tokens
        return request

    @contextmanager
    def _tool_errors(self):
        provider = str(getattr(self, "provider_name", "deepseek"))
        try:
            with track_llm_request(
                provider=provider,
                model=self.model,
                route_key=f"{provider}|{self.model}|{self.base_url}",
            ):
                yield
        except AuthenticationError as exc:
            raise AIAuthenticationError("AI tools API authentication failed.") from exc
        except RateLimitError as exc:
            raise AIRateLimitError("AI tools API rate limit exceeded.") from exc
        except APITimeoutError as exc:
            raise AITimeoutError("AI tools API request timed out.") from exc
        except APIConnectionError as exc:
            raise AIConnectionError("Unable to connect to the AI tools API.") from exc
        except APIStatusError as exc:
            raise AIResponseError(
                "AI tools API request failed.",
                status_code=getattr(exc, "status_code", None),
            ) from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIResponseError("AI tools API returned an invalid response.") from exc

    def complete_tools(
        self, *, messages, tools, tool_choice="auto", temperature=0.2, max_tokens=None
    ) -> ToolCompletion:
        request = self._tool_request(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        with self._tool_errors():
            choice = self._client.chat.completions.create(**request).choices[0]
            message = {"role": "assistant", "content": choice.message.content}
            if choice.message.tool_calls:
                message["tool_calls"] = [
                    call.model_dump(exclude_none=True)
                    for call in choice.message.tool_calls
                ]
            reasoning = getattr(choice.message, "reasoning_content", None)
            if reasoning is not None:
                message["reasoning_content"] = reasoning
            return _completion(message, choice.finish_reason)

    def stream_tools(
        self, *, messages, tools, tool_choice="auto", temperature=0.2, max_tokens=None
    ) -> Iterator[str | ToolCompletion]:
        request = self._tool_request(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        with self._tool_errors():
            response = self._client.chat.completions.create(**request)
            content: list[str] = []
            reasoning: list[str] = []
            calls: dict[int, dict[str, Any]] = {}
            finish = None
            try:
                for event in response:
                    if not event.choices:
                        continue  # An optional final usage event has no choices.
                    choice = event.choices[0]
                    if choice.finish_reason:
                        finish = choice.finish_reason
                    delta = choice.delta
                    text = delta.content
                    if text:
                        content.append(text)
                        yield text
                    thought = getattr(delta, "reasoning_content", None)
                    if thought:
                        reasoning.append(thought)
                    for part in delta.tool_calls or ():
                        if part.index not in calls:
                            if len(calls) >= 16:
                                raise AIResponseError(
                                    "Native stream contains too many tool calls."
                                )
                            calls[part.index] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        call = calls[part.index]
                        if part.id:
                            call["id"] += part.id
                        if part.type and part.type != "function":
                            raise AIResponseError("Unsupported native tool type.")
                        if part.function:
                            call["function"]["name"] += part.function.name or ""
                            call["function"]["arguments"] += (
                                part.function.arguments or ""
                            )
                        if len(call["function"]["arguments"]) > 16_000:
                            raise AIResponseError(
                                "Native tool arguments exceed the size limit."
                            )
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            message = {"role": "assistant", "content": "".join(content) or None}
            if calls:
                message["tool_calls"] = [calls[index] for index in sorted(calls)]
            if reasoning:
                message["reasoning_content"] = "".join(reasoning)
            yield _completion(message, finish)
