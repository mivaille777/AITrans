from types import SimpleNamespace

import pytest

from app.models.translation import TranslationResult
from app.translation.errors import TextNormalizationError, TranslationError
from backend.services import translation_fallback_service as module
from backend.services.translation_fallback_service import TranslationFallbackService


class StubProvider:
    def __init__(self, name: str, calls: list[str], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail
        self.closed = False

    def translate(self, request):
        self.calls.append(self.name)
        if self.fail:
            raise TranslationError(f"{self.name} unavailable")
        return TranslationResult(
            source_text=request.source_text,
            translated_text=f"{self.name}:{request.source_text}",
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.name,
            request_id=request.request_id,
        )

    def close(self):
        self.closed = True


class StubAIService:
    provider_name = "deepseek"
    model = "stub-ai-model"

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.closed = False

    def translate(self, source_text: str, **kwargs):
        self.calls.append("ai")
        return SimpleNamespace(
            output_text=f"ai:{source_text}",
            source_language=kwargs["source_language"],
            target_language=kwargs["target_language"],
            model=self.model,
        )

    def close(self):
        self.closed = True


class StubGateway:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def create_text_service(self, role: str):
        assert role == "translation_ai"
        return StubAIService(self.calls)


def install_providers(
    monkeypatch, calls: list[str], *, youdao_fail: bool, google_fail: bool
):
    monkeypatch.setattr(
        module,
        "YoudaoWebTranslationProvider",
        lambda **_: StubProvider("youdao_web", calls, fail=youdao_fail),
    )
    monkeypatch.setattr(
        module,
        "GoogleWebTranslationProvider",
        lambda **_: StubProvider("google_web", calls, fail=google_fail),
    )


def test_youdao_success_stops_fallback_chain(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=False, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate("hello")

    assert calls == ["youdao_web"]
    assert result.provider == "youdao_web"
    assert result.fallback_level == 0
    assert result.notice == ""


def test_google_runs_only_after_youdao_is_unavailable(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=True, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate("hello")

    assert calls == ["youdao_web", "google_web"]
    assert result.provider == "google_web"
    assert result.fallback_level == 1
    assert "有道翻译当前不可用" in result.notice


def test_ai_runs_only_after_both_web_providers_are_unavailable(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=True, google_fail=True)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate("hello")

    assert calls == ["youdao_web", "google_web", "ai"]
    assert result.provider == "ai"
    assert result.fallback_level == 2
    assert "有道和 Google 翻译当前不可用" in result.notice


def test_manual_google_never_calls_youdao_or_ai(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=False, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate("hello", provider_mode="google_web")

    assert calls == ["google_web"]
    assert result.provider == "google_web"
    assert result.fallback_level == 0
    assert result.notice == ""


def test_manual_youdao_failure_does_not_fallback(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=True, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    with pytest.raises(TranslationError, match="Youdao"):
        service.translate("hello", provider_mode="youdao_web")

    assert calls == ["youdao_web"]


def test_manual_ai_calls_only_ai(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=False, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate("hello", provider_mode="ai")

    assert calls == ["ai"]
    assert result.provider == "ai"
    assert result.fallback_level == 0
    assert result.notice == ""


def test_terminology_preferences_use_ai_instead_of_unconstrained_web(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=False, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    result = service.translate(
        "graph neural network",
        terminology=("graph neural network => 图神经网络",),
    )

    assert calls == ["ai"]
    assert result.provider == "ai"


def test_invalid_source_does_not_call_any_provider(monkeypatch):
    calls: list[str] = []
    install_providers(monkeypatch, calls, youdao_fail=False, google_fail=False)
    service = TranslationFallbackService(llm_gateway=StubGateway(calls))

    with pytest.raises(TextNormalizationError):
        service.translate("   ")

    assert calls == []
