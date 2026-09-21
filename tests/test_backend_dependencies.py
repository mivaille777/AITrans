from __future__ import annotations

from backend.api import dependencies
from backend.services.companion_chat_service import CompanionChatService


def test_default_companion_chat_service_can_be_constructed() -> None:
    dependencies.close_companion_chat_service()

    try:
        service = dependencies.get_companion_chat_service()
    finally:
        dependencies.close_companion_chat_service()

    assert isinstance(service, CompanionChatService)
