from __future__ import annotations

from threading import Lock

from backend.api.dependencies import get_companion_chat_service, get_research_note_service
from backend.api.evidence_ledger_dependencies import get_evidence_ledger_service
from backend.api.research_memory_dependencies import get_research_memory_service
from backend.services.agent_literature_synthesis_service import AgentLiteratureSynthesisService
from backend.services.evidence_review_service import EvidenceReviewService
from backend.services.grounded_synthesis_service import GroundedSynthesisService

_review_service: EvidenceReviewService | None = None
_review_lock = Lock()
_agent_synthesis_service: AgentLiteratureSynthesisService | None = None
_agent_synthesis_lock = Lock()


def get_evidence_review_service() -> EvidenceReviewService:
    global _review_service
    if _review_service is not None:
        return _review_service
    with _review_lock:
        if _review_service is None:
            _review_service = EvidenceReviewService(
                ledger_service=get_evidence_ledger_service()
            )
        return _review_service


def get_agent_literature_synthesis_service() -> AgentLiteratureSynthesisService:
    global _agent_synthesis_service
    if _agent_synthesis_service is not None:
        return _agent_synthesis_service
    with _agent_synthesis_lock:
        if _agent_synthesis_service is None:
            _agent_synthesis_service = AgentLiteratureSynthesisService(
                review_service=get_evidence_review_service(),
                research_memory_service=get_research_memory_service(),
                research_note_service=get_research_note_service(),
                grounded_synthesis_service=GroundedSynthesisService(
                    chat_service=get_companion_chat_service()
                ),
            )
        return _agent_synthesis_service


def close_evidence_review_service() -> None:
    global _review_service, _agent_synthesis_service
    with _agent_synthesis_lock:
        _agent_synthesis_service = None
    with _review_lock:
        _review_service = None


__all__ = [
    "close_evidence_review_service",
    "get_agent_literature_synthesis_service",
    "get_evidence_review_service",
]
