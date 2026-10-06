"""Compose Skill functions with existing provider loops without sharing tool policy.

Skill-only responses are consumed here. Ordinary tool responses remain owned by
the caller's knowledge/ReAct loop, including mandatory tool selection and budgets.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator

from app.ai.errors import AIResponseError
from app.ai.tool_calling import ToolCompletion
from backend.agent_core.exceptions import AgentCancelledError
from backend.services.skill_runtime import MAX_CALLS, SkillSession

SKILL_FUNCTIONS = {"discover_skills", "activate_skill", "read_skill_resource"}


class SkillCallingClient:
    def __init__(
        self,
        client,
        session: SkillSession,
        *,
        on_change: Callable | None = None,
        cancel_event=None,
    ):
        self.client, self.session = client, session
        self.on_change, self.cancel_event = on_change, cancel_event
        self._messages: dict[int, tuple[list, dict]] = {}
        self._ids: set[str] = set()

    def _request(self, kwargs):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AgentCancelledError("Cancelled before Skill decision")
        messages = kwargs["messages"]
        cached = self._messages.get(id(messages))
        message = cached[1] if cached else None
        context = self.session.context()
        if message is None and context:
            message = {"role": "system", "content": context}
            self._messages[id(messages)] = (messages, message)
            messages.insert(1, message)
        elif message is not None:
            message["content"] = context
        # A knowledge-required phase cannot be satisfied by loading a Skill.
        names = (
            self.session.function_names
            if kwargs.get("tool_choice", "auto") == "auto"
            else []
        )
        return dict(
            kwargs,
            tools=list(kwargs.get("tools", []))
            + [self.session.schema(name) for name in names],
        ), names

    def _consume(self, response, messages, names):
        skill_calls = [
            call
            for call in response.tool_calls
            if call["function"]["name"] in SKILL_FUNCTIONS
        ]
        if not skill_calls:
            return response
        ids = [call["id"] for call in response.tool_calls]
        transcript_ids = {
            call["id"] for message in messages for call in message.get("tool_calls", [])
        }
        if len(set(ids)) != len(ids) or set(ids) & (self._ids | transcript_ids):
            raise AIResponseError("Skill response reused a native tool call ID.")
        self._ids.update(ids)
        messages.append(dict(response.message, content=None, tool_calls=skill_calls))
        for call in skill_calls:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise AgentCancelledError("Cancelled before Skill resource access")
            name = call["function"]["name"]
            recorded = len(self.session.calls)
            output = (
                self.session.invoke(name, call["function"]["arguments"])
                if name in names
                else self.session.reject(name)
            )
            if len(self.session.calls) > recorded:
                self.session.calls[-1]["tool_call_id"] = call["id"]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )
            if self.on_change:
                self.on_change()
        ordinary = [
            call
            for call in response.tool_calls
            if call["function"]["name"] not in SKILL_FUNCTIONS
        ]
        return (
            ToolCompletion(dict(response.message, content=None, tool_calls=ordinary))
            if ordinary
            else None
        )

    def complete_tools(self, **kwargs):
        for _ in range(MAX_CALLS + 1):
            request, names = self._request(kwargs)
            response = self.client.complete_tools(**request)
            result = self._consume(response, kwargs["messages"], names)
            if result is not None:
                return result
        raise AIResponseError("Skill decisions exceeded their bounded call budget.")

    def stream_tools(self, **kwargs) -> Iterator:
        for _ in range(MAX_CALLS + 1):
            request, names = self._request(kwargs)
            parts, response = [], None
            stream = self.client.stream_tools(**request)
            try:
                for part in stream:
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        raise AgentCancelledError("Cancelled during Skill decision")
                    if isinstance(part, ToolCompletion):
                        response = part
                    elif isinstance(part, str):
                        # Hold tentative text until we know whether this is a Skill call.
                        parts.append(part)
                if response is None:
                    raise AIResponseError(
                        "Skill stream ended without a native completion."
                    )
                result = self._consume(response, kwargs["messages"], names)
                if result is not None:
                    if not response.tool_calls:
                        yield from parts
                    yield result
                    return
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
        raise AIResponseError("Skill decisions exceeded their bounded call budget.")
