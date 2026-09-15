from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from backend.knowledge.v2_repository import KnowledgeV2Repository


class KnowledgeV2Service:
    """Application service for Knowledge 2.0 semantic objects."""

    def __init__(self, repository: KnowledgeV2Repository) -> None:
        self.repository = repository

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_card(self, *, card_type: str, title: str, summary: str = "", content: dict[str, Any] | None = None, confidence: float = 0.0) -> dict[str, Any]:
        now = self._now()
        return self.repository.create_card({
            "id": self._id("card"),
            "type": card_type,
            "title": title.strip(),
            "summary": summary,
            "content": content or {},
            "confidence": confidence,
            "created_at": now,
            "updated_at": now,
        })

    def list_cards(self) -> list[dict[str, Any]]:
        return self.repository.list_cards()

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        return self.repository.get_card(card_id)

    def get_graph(self) -> dict[str, list[Any]]:
        return self.repository.get_graph()

    def list_agent_events(self) -> list[dict[str, Any]]:
        return self.repository.list_agent_events()

    def record_agent_event(self, *, agent_name: str, action: str, target_id: str, input_data: dict[str, Any] | None = None, output_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.repository.record_agent_event({
            "id": self._id("event"),
            "agent_name": agent_name,
            "action": action,
            "target_id": target_id,
            "input": input_data or {},
            "output": output_data or {},
            "created_at": self._now(),
        })


__all__ = ["KnowledgeV2Service"]
