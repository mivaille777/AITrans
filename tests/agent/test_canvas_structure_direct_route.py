from __future__ import annotations

from types import SimpleNamespace

from backend.services.companion_chat_service import CompanionChatService
from backend.services.product_agent_service import ProductAgentService


class _CaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        return "R1: Insight -> Evidence (supports, manual)."


class _FakeTextService:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.client = _CaptureClient()
        self.provider = SimpleNamespace(client=self.client)

    def close(self) -> None:
        return None


class _EmptyRegistry:
    def list_tools(self):
        return ()

    def get_tool(self, _name: str):
        return None


class _SemanticRouterMustNotRun:
    provider_name = "should-not-run"
    model = "should-not-run"
    prompt_id = "should-not-run"

    def route(self, **_kwargs):  # pragma: no cover - failure is the assertion
        raise AssertionError("Canvas structure inspection must bypass the semantic planner.")


def test_canvas_structure_query_uses_direct_answer_path() -> None:
    text_service = _FakeTextService()
    service = ProductAgentService(
        registry=_EmptyRegistry(),
        chat_service=CompanionChatService(text_service=text_service),
        semantic_router=_SemanticRouterMustNotRun(),
    )

    result = service.run(
        session_id="canvas-direct-route",
        user_message=(
            "List every explicit Canvas relation available in your current context. "
            "For each relation, give relation id, source card title, target card title, "
            "relation type, label, and origin. Do not infer missing relations."
        ),
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
        context_mode="general",
        knowledge_context={
            "canvas": {
                "board_id": "board-1",
                "board_name": "Research Board",
                "scope_label": "Selected cards",
            },
            "cards": [
                {
                    "item_id": "insight-1",
                    "item_type": "insight",
                    "title": "Insight",
                    "summary": "Bounded local refinement.",
                    "document_id": "doc-1",
                },
                {
                    "item_id": "evidence-1",
                    "item_type": "evidence",
                    "title": "Evidence",
                    "summary": "Paper evidence.",
                    "document_id": "doc-1",
                },
            ],
            "relations": [
                {
                    "relation_id": "R1",
                    "source_item_id": "insight-1",
                    "source_title": "Insight",
                    "target_item_id": "evidence-1",
                    "target_title": "Evidence",
                    "relation_type": "supports",
                    "label": "manual edge",
                    "origin": "manual",
                    "confidence": None,
                }
            ],
        },
        request_id=1,
    )

    assert result.status == "completed"
    assert result.route is not None
    assert result.route.source == "deterministic"
    assert result.route.kind == "answer"
    assert result.output_text.startswith("R1:")
    assert len(text_service.client.calls) == 1
