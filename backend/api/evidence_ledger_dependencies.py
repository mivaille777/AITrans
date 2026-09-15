from __future__ import annotations

from threading import Lock

from backend.api.dependencies import get_research_note_service
from backend.api.research_memory_dependencies import get_research_memory_service
from backend.services.cross_document_research_service import CrossDocumentResearchService
from backend.services.evidence_ledger_service import EvidenceLedgerService

_evidence_ledger_service: EvidenceLedgerService | None = None
_evidence_ledger_service_lock = Lock()


def get_evidence_ledger_service() -> EvidenceLedgerService:
    global _evidence_ledger_service
    if _evidence_ledger_service is not None:
        return _evidence_ledger_service
    with _evidence_ledger_service_lock:
        if _evidence_ledger_service is None:
            notes = get_research_note_service()
            memory = get_research_memory_service()
            cross_document = CrossDocumentResearchService(
                research_memory_service=memory,
                research_note_service=notes,
            )
            _evidence_ledger_service = EvidenceLedgerService(
                research_memory_service=memory,
                cross_document_service=cross_document,
            )
        return _evidence_ledger_service


def close_evidence_ledger_service() -> None:
    global _evidence_ledger_service
    with _evidence_ledger_service_lock:
        _evidence_ledger_service = None


__all__ = [
    "close_evidence_ledger_service",
    "get_evidence_ledger_service",
]
