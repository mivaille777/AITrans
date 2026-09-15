from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agent_core.context import ReadingContextProvider
from backend.agent_core.product_adapter import ProductAgentRuntimeAdapter
from backend.agent_core.runtime import AgentRuntime
from backend.agent_graph.reading_agent_graph import ReadingAgentGraph
from backend.api.agent import _state_from_run_request
from backend.models.agent_runtime import AgentRouteDecision
from backend.models.agent_tools import AgentRunRequest
from backend.services.companion_chat_service import CompanionChatService
from backend.services.product_agent_service import ProductAgentService


class _PromptCaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return "The Canvas relation context is available."


class _FakeTextService:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.client = _PromptCaptureClient()
        self.provider = SimpleNamespace(client=self.client)

    def close(self) -> None:
        return None


class _EmptyRegistry:
    def list_tools(self):
        return ()

    def get_tool(self, _name: str):
        return None


class _AnswerRouter:
    def route(self, *, user_message: str, tools, **_):
        assert user_message
        assert tools == ()
        return AgentRouteDecision(
            kind="answer",
            source="deterministic",
            intent="answer",
            user_visible_reason="Answer directly from the attached context.",
        )


class _UnusedReadingResolver:
    def resolve_for_text(self, _text: str):  # pragma: no cover - general mode must not call it
        raise AssertionError("General Canvas context must not use ambient reading resolution.")


def _canvas_request() -> AgentRunRequest:
    return AgentRunRequest(
        session_id="canvas-e2e-session",
        trace_id="canvas-e2e-trace",
        context_mode="general",
        user_message="List every explicit Canvas relation available in your current context.",
        source_text="",
        translated_text="",
        source_language="auto",
        target_language="zh-CN",
        resource_url="",
        resource_title="",
        section_heading="",
        context_before="",
        context_after="",
        source_kind="knowledge_document",
        knowledge_context={
            "canvas": {
                "board_id": "board-1",
                "board_name": "test1",
                "scope_label": "Canvas",
            },
            "cards": [
                {
                    "item_id": "insight-1",
                    "item_type": "insight",
                    "title": "Research insight",
                    "summary": "An LLM performs bounded local refinement.",
                    "document_id": "doc-1",
                },
                {
                    "item_id": "evidence-1",
                    "item_type": "evidence",
                    "title": "PID evidence",
                    "summary": "Evidence from the source paper.",
                    "document_id": "doc-1",
                },
            ],
            "relations": [
                {
                    "relation_id": "relation-1",
                    "source_item_id": "insight-1",
                    "source_title": "Research insight",
                    "target_item_id": "evidence-1",
                    "target_title": "PID evidence",
                    "relation_type": "supports",
                    "label": "manual test edge",
                    "origin": "manual",
                    "confidence": None,
                }
            ],
        },
        request_id=1,
    )


def test_canvas_context_reaches_final_model_prompt_without_reading_mode() -> None:
    text_service = _FakeTextService()
    chat_service = CompanionChatService(text_service=text_service)
    product_service = ProductAgentService(
        registry=_EmptyRegistry(),
        chat_service=chat_service,
        router=_AnswerRouter(),
    )
    adapter = ProductAgentRuntimeAdapter(product_service)
    graph = ReadingAgentGraph(adapter)
    runtime = AgentRuntime(
        context_provider=ReadingContextProvider(_UnusedReadingResolver()),
        workflow_adapter=graph,
    )

    state = runtime.execute(_state_from_run_request(_canvas_request()))

    assert state.response["status"] == "completed"
    assert state.response["output_text"] == "The Canvas relation context is available."
    assert len(text_service.client.calls) == 1

    prompt = str(text_service.client.calls[0]["user_prompt"])
    _prefix, serialized = prompt.split("\n\n", 1)
    payload = json.loads(serialized)

    # This proves the contract no longer relies on Reading mode or source_text.
    assert payload["selected_context"]["source_text"] == ""
    assert payload["reading_context"] is None

    knowledge = payload["knowledge_context"]
    assert knowledge["canvas"] == {
        "board_id": "board-1",
        "board_name": "test1",
        "scope_label": "Canvas",
    }
    assert [card["item_id"] for card in knowledge["cards"]] == [
        "insight-1",
        "evidence-1",
    ]
    assert knowledge["relations"] == [
        {
            "relation_id": "relation-1",
            "source_item_id": "insight-1",
            "source_title": "Research insight",
            "target_item_id": "evidence-1",
            "target_title": "PID evidence",
            "relation_type": "supports",
            "label": "manual test edge",
            "origin": "manual",
            "confidence": None,
        }
    ]
    assert payload["runtime_policy"]["knowledge_relation_trust"] == (
        "organizational_context_not_factual_evidence"
    )
