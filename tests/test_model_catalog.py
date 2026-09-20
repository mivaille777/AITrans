from __future__ import annotations

from types import SimpleNamespace


def test_model_catalog_uses_current_provider_key_and_deduplicates(monkeypatch) -> None:
    from app.ai import model_catalog

    calls: dict[str, object] = {}

    class FakeClient:
        models = SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[
                    SimpleNamespace(id="llama-z"),
                    {"id": "llama-a"},
                    SimpleNamespace(id="llama-z"),
                ]
            )
        )

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = FakeClient()

    def build_client(**kwargs):
        calls.update(kwargs)
        return client

    monkeypatch.setattr(model_catalog, "OpenAI", build_client)

    def get_key(provider, **_):
        calls["provider"] = provider
        return "secret"

    monkeypatch.setattr(model_catalog, "get_provider_api_key", get_key)

    model_ids = model_catalog.list_available_model_ids(
        provider="openai_compatible",
        base_url="https://gateway.example/v1/",
    )

    assert model_ids == ("llama-a", "llama-z")
    assert calls["provider"] == "openai_compatible"
    assert calls["base_url"] == "https://gateway.example/v1"
    assert calls["api_key"] == "secret"
    assert client.closed is True
