from __future__ import annotations

from types import SimpleNamespace

from app.ai.chat.models import ChatContext, ChatRequest
from app.ai.chat.stream_service import ProviderStreamingAIChatService


class _FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.requests.append(dict(kwargs))
        return [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="，世界"))]
            ),
        ]


class _FakeClientWrapper:
    model = "fake-model"

    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self._client = SimpleNamespace(
            chat=SimpleNamespace(completions=self.completions)
        )

    def complete(self, **_kwargs) -> str:
        return "fallback"


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.client = _FakeClientWrapper()


class _FakeTextService:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.provider = _FakeProvider()


def test_streaming_chat_service_yields_incremental_provider_content() -> None:
    text_service = _FakeTextService()
    service = ProviderStreamingAIChatService(text_service)
    request = ChatRequest(
        session_id="session-1",
        user_message="问候一下",
        context=ChatContext(source_text="context"),
        request_id=5,
    )

    chunks = list(service.stream(request))

    assert chunks == ["你好", "，世界"]
    sent = text_service.provider.client.completions.requests[0]
    assert sent["stream"] is True
    assert sent["model"] == "fake-model"
