from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.models.agent_runtime import AgentEvidenceItem
from backend.rag.models import RetrievalCandidate, RetrievalResult


def _location(candidate: RetrievalCandidate) -> str:
    page_number = candidate.chunk.page_number
    section = candidate.chunk.section_heading.strip()
    if page_number is not None and section:
        return f"Page {page_number} · Section {section}"
    if page_number is not None:
        return f"Page {page_number}"
    if section:
        return f"Section {section}"
    return ""


def _score(candidate: RetrievalCandidate) -> float | None:
    for score in (
        candidate.rerank_score,
        candidate.fusion_score,
        candidate.dense_score,
        candidate.sparse_score,
    ):
        if score is not None:
            return score
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    return str(value)


def build_evidence_item(
    candidate: RetrievalCandidate,
    *,
    retrieval_strategy: str = "",
    retrieval_metadata: Mapping[str, Any] | None = None,
) -> AgentEvidenceItem:
    """Map one retrieval candidate to a stable Agent evidence contract."""

    chunk = candidate.chunk
    modality = str(chunk.metadata.get("modality", "text") or "text")
    element_metadata = chunk.metadata.get("element_metadata")
    if not isinstance(element_metadata, Mapping):
        element_metadata = {}
    metadata = _json_safe(
        {
            "retrieval_strategy": retrieval_strategy,
            "retrieval": dict(retrieval_metadata or {}),
            "candidate": dict(candidate.metadata),
            "rank": candidate.rank,
            "page_number": chunk.page_number,
            "section_heading": chunk.section_heading,
            "modality": modality,
            "element_id": chunk.metadata.get("element_id", ""),
            "asset_uri": chunk.metadata.get("asset_uri", ""),
            "bbox": chunk.metadata.get("bbox"),
            "caption": chunk.metadata.get("caption", ""),
            "visual_grounding_available": bool(
                chunk.metadata.get("visual_grounding_available", False)
            ),
            "visual_description": element_metadata.get("visual_description", ""),
            "visual_description_status": element_metadata.get(
                "visual_description_status", ""
            ),
            "visual_description_provider": element_metadata.get(
                "visual_description_provider", ""
            ),
            "visual_description_model": element_metadata.get(
                "visual_description_model", ""
            ),
            "visual_description_prompt_id": element_metadata.get(
                "visual_description_prompt_id", ""
            ),
            "scores": {
                "rerank": candidate.rerank_score,
                "fusion": candidate.fusion_score,
                "dense": candidate.dense_score,
                "sparse": candidate.sparse_score,
            },
        }
    )
    return AgentEvidenceItem(
        evidence_id=f"evidence:{chunk.chunk_id}",
        source_type="knowledge",
        source_id=chunk.document_id,
        title=chunk.title,
        resource_url=chunk.source_uri,
        location=_location(candidate),
        excerpt=chunk.text,
        score=_score(candidate),
        metadata=metadata,
    )


def build_agent_evidence(result: RetrievalResult) -> list[AgentEvidenceItem]:
    """Map a ranked retrieval result without asking an LLM to invent provenance."""

    return [
        build_evidence_item(
            candidate,
            retrieval_strategy=result.retrieval_strategy,
            retrieval_metadata=result.metadata,
        )
        for candidate in result.candidates
    ]


__all__ = ["build_agent_evidence", "build_evidence_item"]
