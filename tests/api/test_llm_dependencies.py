from __future__ import annotations

from backend.api import llm_dependencies


class _FakeTextService:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _FakeGateway:
    def __init__(self, text_service: _FakeTextService) -> None:
        self.text_service = text_service
        self.created_roles: list[str] = []

    def create_text_service(self, role: str) -> _FakeTextService:
        self.created_roles.append(role)
        return self.text_service


def test_planner_text_service_is_created_lazily_and_cached(monkeypatch) -> None:
    text_service = _FakeTextService()
    gateway = _FakeGateway(text_service)
    monkeypatch.setattr(llm_dependencies, "_gateway", gateway)
    monkeypatch.setattr(llm_dependencies, "_planner_text_service", None)

    first = llm_dependencies.get_planner_text_service()
    second = llm_dependencies.get_planner_text_service()
    planner = llm_dependencies.build_rag_query_planner()

    assert first is second is text_service
    assert planner._text_service is text_service
    assert gateway.created_roles == ["planner"]


def test_reset_releases_cached_planner_and_gateway(monkeypatch) -> None:
    text_service = _FakeTextService()
    gateway = _FakeGateway(text_service)
    monkeypatch.setattr(llm_dependencies, "_gateway", gateway)
    monkeypatch.setattr(llm_dependencies, "_planner_text_service", text_service)

    llm_dependencies.reset_llm_dependencies()

    assert text_service.close_count == 1
    assert llm_dependencies._gateway is None
    assert llm_dependencies._planner_text_service is None
    assert gateway.created_roles == []
