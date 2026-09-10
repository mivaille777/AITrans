from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agent_core.state import AgentState
from backend.services.companion_ownership_service import (
    CompanionConversationOwnershipService,
)
from backend.services.conversation_store_service import (
    ConversationStoreService,
    StoredConversation,
)


@dataclass(frozen=True, slots=True)
class AgentConversationRun:
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    history: tuple[tuple[str, str], ...]
    owner_id: str
    request_id: int


class AgentConversationBusyError(RuntimeError):
    def __init__(self, reason: str, owner_surface: str = "unknown") -> None:
        self.reason = str(reason or "conversation_busy")
        self.owner_surface = str(owner_surface or "unknown")
        super().__init__(self._message())

    def _message(self) -> str:
        if self.reason == "conversation_busy":
            surface = self.owner_surface if self.owner_surface != "unknown" else "another window"
            return f"This conversation is already replying in {surface}."
        if self.reason in {"duplicate_request", "duplicate_active_request"}:
            return "Duplicate Agent request ignored."
        return "Unable to acquire conversation execution ownership."


class AgentConversationService:
    """Bind Agent runs to the durable Companion conversation lifecycle.

    Conversation persistence remains owned by ``ConversationStoreService`` /
    ``ConversationLifecycleService``. This service only coordinates one Agent
    run with that existing store: load history, begin an exchange, keep the
    active context domain current, and commit one terminal assistant state.
    """

    _AGENT_CONTEXT_MODES = {"general", "reading", "knowledge", "research", "translation"}

    def __init__(
        self,
        *,
        store: ConversationStoreService,
        ownership: CompanionConversationOwnershipService,
    ) -> None:
        self._store = store
        self._ownership = ownership

    @staticmethod
    def _history(conversation: StoredConversation | None) -> tuple[tuple[str, str], ...]:
        if conversation is None:
            return ()
        items: list[tuple[str, str]] = []
        for message in conversation.messages:
            role = str(message.role or "").strip()
            content = str(message.content or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if str(message.status or "").strip().lower() != "complete":
                continue
            items.append((role, content))
        return tuple(items[-32:])

    @staticmethod
    def _owner_id(state: AgentState) -> str:
        explicit = str(state.browser_context.get("client_id", "") or "").strip()
        return explicit or f"agent:{state.session_id or state.run_id}"

    @staticmethod
    def _owner_surface(state: AgentState) -> str:
        value = str(state.browser_context.get("client_surface", "unknown") or "unknown")
        return value if value in {"main", "overlay", "unknown"} else "unknown"

    @classmethod
    def _agent_context_mode(cls, state: AgentState) -> str:
        mode = str(state.browser_context.get("context_mode", "reading") or "reading").strip().lower()
        return mode if mode in cls._AGENT_CONTEXT_MODES else "reading"

    @classmethod
    def _conversation_context_mode(cls, state: AgentState) -> str:
        # The durable Companion store currently exposes General vs Reading.
        # Knowledge/Research/Translation are Agent execution domains and must
        # not masquerade as Reading-grounded conversations in AI Chat.
        return "reading" if cls._agent_context_mode(state) == "reading" else "general"

    def _acquire(
        self,
        conversation_id: str,
        *,
        owner_id: str,
        owner_surface: str,
        request_id: int,
    ) -> None:
        claim = self._ownership.acquire(
            conversation_id,
            owner_id=owner_id,
            owner_surface=owner_surface,
            request_id=request_id,
        )
        if claim.acquired:
            return
        surface = claim.lease.owner_surface if claim.lease is not None else "unknown"
        raise AgentConversationBusyError(claim.reason, surface)

    def _release(self, run: AgentConversationRun) -> None:
        self._ownership.release(
            run.conversation_id,
            owner_id=run.owner_id,
            request_id=run.request_id,
        )

    def begin(self, state: AgentState) -> AgentConversationRun:
        context = dict(state.browser_context)
        requested_id = str(context.get("conversation_id", "") or "").strip()
        request_id = max(0, int(context.get("request_id", 0) or 0))
        existing = self._store.get(requested_id) if requested_id else None
        history = self._history(existing)
        owner_id = self._owner_id(state)
        owner_surface = self._owner_surface(state)
        acquired_id = ""
        conversation_context_mode = self._conversation_context_mode(state)
        reading_attached = conversation_context_mode == "reading"

        if existing is not None:
            self._acquire(
                existing.conversation_id,
                owner_id=owner_id,
                owner_surface=owner_surface,
                request_id=request_id,
            )
            acquired_id = existing.conversation_id

        kwargs = {
            "conversation_id": existing.conversation_id if existing is not None else requested_id,
            "session_id": state.session_id or "agent-session",
            "user_message": state.user_input,
            "request_id": request_id,
            "source_text": state.selected_text if reading_attached else "",
            "translated_text": str(context.get("translated_text", "") or "") if reading_attached else "",
            "source_language": str(context.get("source_language", "auto") or "auto"),
            "target_language": str(context.get("target_language", "zh-CN") or "zh-CN"),
            "resource_url": str(context.get("resource_url", "") or "") if reading_attached else "",
            "resource_title": str(context.get("resource_title", "") or "") if reading_attached else "",
            "section_heading": str(context.get("section_heading", "") or "") if reading_attached else "",
            "context_before": str(context.get("context_before", "") or "") if reading_attached else "",
            "context_after": str(context.get("context_after", "") or "") if reading_attached else "",
            "source_kind": str(context.get("source_kind", "desktop") or "desktop") if reading_attached else "",
        }

        exchange = None
        try:
            context_aware = getattr(self._store, "begin_exchange_with_context_mode", None)
            if callable(context_aware):
                exchange = context_aware(context_mode=conversation_context_mode, **kwargs)
            else:
                exchange = self._store.begin_exchange(**kwargs)

            if not acquired_id:
                self._acquire(
                    exchange.conversation_id,
                    owner_id=owner_id,
                    owner_surface=owner_surface,
                    request_id=request_id,
                )
                acquired_id = exchange.conversation_id

            update_context = getattr(self._store, "update_context", None)
            if callable(update_context):
                update_context(
                    exchange.conversation_id,
                    context_mode=conversation_context_mode,
                    source_text=kwargs["source_text"],
                    translated_text=kwargs["translated_text"],
                    source_language=kwargs["source_language"],
                    target_language=kwargs["target_language"],
                    resource_url=kwargs["resource_url"],
                    resource_title=kwargs["resource_title"],
                    section_heading=kwargs["section_heading"],
                    context_before=kwargs["context_before"],
                    context_after=kwargs["context_after"],
                    source_kind=kwargs["source_kind"],
                )

            return AgentConversationRun(
                conversation_id=exchange.conversation_id,
                user_message_id=exchange.user_message_id,
                assistant_message_id=exchange.assistant_message_id,
                history=history,
                owner_id=owner_id,
                request_id=request_id,
            )
        except Exception:
            if exchange is not None:
                self._store.finalize_message(
                    exchange.assistant_message_id,
                    status="error",
                    content="",
                    error_code="conversation_setup",
                )
            if acquired_id:
                self._ownership.release(
                    acquired_id,
                    owner_id=owner_id,
                    request_id=request_id,
                )
            raise

    def apply_to_state(self, state: AgentState, run: AgentConversationRun) -> AgentState:
        return state.apply_conversation(
            conversation_id=run.conversation_id,
            history=run.history,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            context_mode=self._conversation_context_mode(state),
        )

    def complete(self, run: AgentConversationRun, state: AgentState) -> None:
        try:
            status = str(state.response.get("status", "completed") or "completed")
            if status == "confirmation_required":
                self._store.finalize_message(
                    run.assistant_message_id,
                    status="cancelled",
                    content="",
                    error_code="confirmation_required",
                )
                rewind = getattr(self._store, "rewind_from_user_message", None)
                if callable(rewind):
                    rewind(run.conversation_id, run.user_message_id)
                return

            self._store.finalize_message(
                run.assistant_message_id,
                status="complete",
                content=str(state.response.get("output_text", "") or ""),
                provider=str(state.response.get("provider", "") or ""),
                model=str(state.response.get("model", "") or ""),
            )
        finally:
            self._release(run)

    def fail(self, run: AgentConversationRun, exc: Exception) -> None:
        try:
            self._store.finalize_message(
                run.assistant_message_id,
                status="error",
                content="",
                error_code=type(exc).__name__,
            )
        finally:
            self._release(run)

    def cancel(self, run: AgentConversationRun) -> None:
        try:
            self._store.finalize_message(
                run.assistant_message_id,
                status="cancelled",
                content="",
                error_code="user_cancelled",
            )
        finally:
            self._release(run)


__all__ = [
    "AgentConversationBusyError",
    "AgentConversationRun",
    "AgentConversationService",
]
