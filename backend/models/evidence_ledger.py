from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceLedgerEntryKind = Literal["claim", "relation"]
EvidenceLedgerLinkRole = Literal["supporting", "conflicting"]
EvidenceLedgerStatus = Literal["supported", "contested", "insufficient", "stale"]


class EvidenceLedgerContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceLedgerLink(EvidenceLedgerContract):
    link_id: str = Field(min_length=1, max_length=128)
    role: EvidenceLedgerLinkRole
    support_kind: Literal["claim", "relation"]
    claim_id: str = Field(default="", max_length=128)
    relation_id: str = Field(default="", max_length=128)
    evidence_id: str = Field(min_length=1, max_length=128)
    note_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=64)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    captured_source_status: str = Field(default="legacy_unknown", max_length=64)


class EvidenceLedgerEntry(EvidenceLedgerContract):
    entry_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    entry_kind: EvidenceLedgerEntryKind
    statement: str = Field(min_length=1, max_length=4000)
    normalized_statement: str = Field(min_length=1, max_length=4000)
    origin_kind: str = Field(default="", max_length=64)
    origin_id: str = Field(default="", max_length=128)
    query: str = Field(default="", max_length=4000)
    created_at: str = Field(min_length=1, max_length=64)
    updated_at: str = Field(min_length=1, max_length=64)
    links: list[EvidenceLedgerLink] = Field(default_factory=list, max_length=512)


class EvidenceLedgerValidation(EvidenceLedgerContract):
    status: EvidenceLedgerStatus
    usable_support_count: int = Field(default=0, ge=0)
    usable_conflict_count: int = Field(default=0, ge=0)
    supporting_document_count: int = Field(default=0, ge=0)
    conflicting_document_count: int = Field(default=0, ge=0)
    stale_link_count: int = Field(default=0, ge=0)
    missing_link_count: int = Field(default=0, ge=0)
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    checked_at: str = Field(min_length=1, max_length=64)


class EvidenceLedgerItem(EvidenceLedgerContract):
    entry: EvidenceLedgerEntry
    validation: EvidenceLedgerValidation


class EvidenceLedgerSnapshot(EvidenceLedgerContract):
    workspace_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4000)
    entry_count: int = Field(default=0, ge=0)
    supported_count: int = Field(default=0, ge=0)
    contested_count: int = Field(default=0, ge=0)
    insufficient_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    items: list[EvidenceLedgerItem] = Field(default_factory=list, max_length=256)


__all__ = [
    "EvidenceLedgerEntry",
    "EvidenceLedgerEntryKind",
    "EvidenceLedgerItem",
    "EvidenceLedgerLink",
    "EvidenceLedgerLinkRole",
    "EvidenceLedgerSnapshot",
    "EvidenceLedgerStatus",
    "EvidenceLedgerValidation",
]
