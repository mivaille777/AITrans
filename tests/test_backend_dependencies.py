from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api import dependencies
from backend.services.companion_chat_service import CompanionChatService


def test_default_companion_chat_service_can_be_constructed() -> None:
    dependencies.close_companion_chat_service()

    try:
        service = dependencies.get_companion_chat_service()
    finally:
        dependencies.close_companion_chat_service()

    assert isinstance(service, CompanionChatService)


@pytest.mark.parametrize(("rewrite", "router"), [(False, True), (True, False)])
def test_companion_query_flags_bind_settings_without_loading_rag(monkeypatch, rewrite, router):
    dependencies.close_companion_chat_service()
    monkeypatch.setattr(
        dependencies,
        "SettingsManager",
        lambda: SimpleNamespace(data={"rag": {
            "query_rewrite_enabled": rewrite, "query_router_enabled": router,
        }}),
    )
    try:
        service = dependencies.get_companion_chat_service()
        assert service._rag_rewrite_enabled is rewrite
        assert service._rag_query_router.enabled is router
        assert service._retrieval_service is None
        assert service._query_planner is None
    finally:
        dependencies.close_companion_chat_service()
