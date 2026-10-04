from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.models import RagContractModel


class EvidenceQuote(RagContractModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class AtomicClaimRequirement(RagContractModel):
    claim_id: str = Field(min_length=1)
    # Any alternative suffices; every quote inside that alternative is required.
    alternatives: list[list[EvidenceQuote]] = Field(min_length=1)


@dataclass(frozen=True)
class EvidenceVerification:
    status: Literal["sufficient", "relevant_insufficient", "absent"]
    missing_claim_ids: tuple[str, ...]
    reason: str


def verify_claim_evidence(
    requirements: Sequence[AtomicClaimRequirement], excerpts: Mapping[str, str],
) -> EvidenceVerification:
    """Check independently specified verbatim evidence, never ID overlap alone."""
    if not excerpts:
        return EvidenceVerification("absent", tuple(item.claim_id for item in requirements), "no_evidence")
    if not requirements:
        return EvidenceVerification("relevant_insufficient", (), "claim_requirements_not_supplied")
    missing = tuple(
        item.claim_id for item in requirements
        if not any(
            alternative and all(quote.quote in excerpts.get(quote.chunk_id, "") for quote in alternative)
            for alternative in item.alternatives
        )
    )
    return EvidenceVerification(
        "relevant_insufficient" if missing else "sufficient", missing,
        "incomplete_or_mismatched_evidence" if missing else "complete_verbatim_evidence",
    )


def verify_evidence_provenance(evidence: Sequence[AgentEvidenceItem]) -> None:
    """Reject corrupted versioned excerpts; legacy sources remain compatible."""
    from hashlib import sha256

    from backend.rag.exceptions import RagInvariantError
    from backend.rag.source_span import SourceSpan

    for item in evidence:
        raw_span = item.metadata.get("source_span")
        if raw_span is None:
            continue
        span = SourceSpan.model_validate(raw_span)
        if span.quote_hash != sha256(item.excerpt.encode("utf-8")).hexdigest():
            raise RagInvariantError("citation source span does not match evidence excerpt")
