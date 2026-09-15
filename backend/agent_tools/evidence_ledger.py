from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

from pydantic import BaseModel, Field

from backend.agent_tools.base import (
    AgentToolExecutionResult,
    AgentToolInvocationContext,
    AgentToolModel,
    TypedAgentToolDefinition,
    typed_tool_definition,
)
from backend.models.agent_runtime import AgentCitationRef, AgentEvidenceItem
from backend.rag.citation_service import build_evidence_citations

_LEDGER_QUERY_LIMIT = 4_000
_LEDGER_TEXT_LIMIT = 1_600
_USABLE_SOURCE_STATUSES = frozenset({"fresh", "legacy_unknown"})


class SearchEvidenceLedgerArgs(AgentToolModel):
    query: str = Field(default="", max_length=_LEDGER_QUERY_LIMIT)


class SaveEvidenceLedgerArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=_LEDGER_QUERY_LIMIT)


class SearchEvidenceLedgerToolData(AgentToolModel):
    workspace_id: str = Field(default="", max_length=128)
    query: str = Field(default="", max_length=_LEDGER_QUERY_LIMIT)
    entry_count: int = Field(default=0, ge=0)
    supported_count: int = Field(default=0, ge=0)
    contested_count: int = Field(default=0, ge=0)
    insufficient_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    ledger: dict[str, Any] = Field(default_factory=dict)
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)


class SaveEvidenceLedgerToolData(AgentToolModel):
    workspace_id: str = Field(default="", max_length=128)
    query: str = Field(default="", max_length=_LEDGER_QUERY_LIMIT)
    saved_entry_count: int = Field(default=0, ge=0)
    saved_entry_ids: list[str] = Field(default_factory=list, max_length=256)


def _bounded(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text if len(text) <= limit else text[:limit].rstrip()


class EvidenceLedgerAgentTools:
    """Agent boundary over Stage 19 durable, revalidated research conclusions."""

    def __init__(
        self,
        *,
        evidence_ledger_service: Any,
        research_memory_service: Any,
        research_note_service: Any,
    ) -> None:
        self._ledger = evidence_ledger_service
        self._memory = research_memory_service
        self._notes = research_note_service

    def search_evidence_ledger(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(SearchEvidenceLedgerArgs, args)
        workspace_id = context.workspace_id.strip()
        if not workspace_id:
            return AgentToolExecutionResult(
                tool_name="search_evidence_ledger",
                output_text="Evidence Ledger search requires an active Research Workspace.",
                effect="read",
                request_id=context.request_id,
                data={
                    "workspace_id": "",
                    "query": typed.query,
                    "entry_count": 0,
                    "supported_count": 0,
                    "contested_count": 0,
                    "insufficient_count": 0,
                    "stale_count": 0,
                    "ledger": {},
                    "evidence": [],
                    "citations": [],
                },
            )

        ledger = self._ledger.snapshot(
            workspace_id=workspace_id,
            query=typed.query,
            limit=100,
        )
        memory = self._memory.snapshot(workspace_id=workspace_id, limit=500)
        evidence_by_id = {item.evidence_id: item for item in memory.evidence}

        contexts: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "entry_ids": set(),
                "roles": set(),
                "statuses": set(),
                "score": 0.0,
            }
        )
        for item in ledger.items:
            if item.validation.status == "stale":
                continue
            for link in item.entry.links:
                source = evidence_by_id.get(link.evidence_id)
                if source is None or source.note_id != link.note_id:
                    continue
                status = str(
                    self._memory.source_status(
                        workspace_id=workspace_id,
                        note_id=link.note_id,
                    )
                    or "legacy_unknown"
                )
                if status not in _USABLE_SOURCE_STATUSES:
                    continue
                metadata = contexts[link.evidence_id]
                metadata["entry_ids"].add(item.entry.entry_id)
                metadata["roles"].add(link.role)
                metadata["statuses"].add(item.validation.status)
                metadata["score"] = max(metadata["score"], float(link.confidence))

        evidence: list[AgentEvidenceItem] = []
        for evidence_id, metadata in sorted(
            contexts.items(),
            key=lambda item: (float(item[1]["score"]), item[0]),
            reverse=True,
        ):
            source = evidence_by_id.get(evidence_id)
            if source is None:
                continue
            note = self._notes.get(source.note_id)
            if note is None:
                continue
            evidence.append(
                AgentEvidenceItem(
                    evidence_id=f"evidence-ledger:{source.evidence_id}",
                    source_type="research_memory",
                    source_id=source.note_id,
                    title=_bounded(note.display_title, 1024),
                    resource_url=_bounded(getattr(note, "resource_url", ""), 4096),
                    location=_bounded(getattr(note, "section_heading", ""), 1024),
                    excerpt=_bounded(source.excerpt, _LEDGER_TEXT_LIMIT),
                    score=max(0.0, min(1.0, float(metadata["score"]))),
                    metadata={
                        "workspace_id": workspace_id,
                        "note_id": source.note_id,
                        "claim_id": source.claim_id,
                        "structured_evidence_id": source.evidence_id,
                        "ledger_entry_ids": sorted(metadata["entry_ids"]),
                        "ledger_roles": sorted(metadata["roles"]),
                        "ledger_statuses": sorted(metadata["statuses"]),
                        "source_verified": True,
                    },
                )
            )
        citations = build_evidence_citations(evidence)

        lines = [f"Evidence Ledger contains {ledger.entry_count} matching claim(s)."]
        lines.append(
            "Current status: "
            f"{ledger.supported_count} supported, {ledger.contested_count} contested, "
            f"{ledger.insufficient_count} insufficient, {ledger.stale_count} stale."
        )
        for item in ledger.items[:12]:
            lines.append(
                f"- [{item.validation.status}] {item.entry.statement} "
                f"({item.validation.supporting_document_count} supporting document(s), "
                f"{item.validation.conflicting_document_count} conflicting document(s))"
            )
        if not ledger.items:
            lines.append("No persisted Evidence Ledger claim matched this query.")

        return AgentToolExecutionResult(
            tool_name="search_evidence_ledger",
            output_text="\n".join(lines),
            effect="read",
            request_id=context.request_id,
            data={
                "workspace_id": workspace_id,
                "query": typed.query,
                "entry_count": ledger.entry_count,
                "supported_count": ledger.supported_count,
                "contested_count": ledger.contested_count,
                "insufficient_count": ledger.insufficient_count,
                "stale_count": ledger.stale_count,
                "ledger": ledger.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "citations": [item.model_dump(mode="json") for item in citations],
            },
        )

    def save_evidence_ledger(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(SaveEvidenceLedgerArgs, args)
        workspace_id = context.workspace_id.strip()
        if not workspace_id:
            return AgentToolExecutionResult(
                tool_name="save_evidence_ledger",
                output_text="Saving to the Evidence Ledger requires an active Research Workspace.",
                effect="write",
                request_id=context.request_id,
                data={
                    "workspace_id": "",
                    "query": typed.query,
                    "saved_entry_count": 0,
                    "saved_entry_ids": [],
                },
            )
        entry_ids = self._ledger.capture_query(
            workspace_id=workspace_id,
            query=typed.query,
        )
        return AgentToolExecutionResult(
            tool_name="save_evidence_ledger",
            output_text=(
                f"Saved {len(entry_ids)} cross-document research claim(s) to the Evidence Ledger."
                if entry_ids
                else "No deterministic cross-document findings were available to save."
            ),
            effect="write",
            request_id=context.request_id,
            data={
                "workspace_id": workspace_id,
                "query": typed.query,
                "saved_entry_count": len(entry_ids),
                "saved_entry_ids": list(entry_ids),
            },
        )


def build_evidence_ledger_tool_definitions(
    tools: EvidenceLedgerAgentTools,
) -> tuple[TypedAgentToolDefinition, ...]:
    return (
        typed_tool_definition(
            name="search_evidence_ledger",
            title="Search Evidence Ledger",
            description=(
                "Read persisted, revalidated research Claims from the active Research Workspace. "
                "Returns current supported/contested/insufficient/stale status plus live source "
                "Evidence and citations. Workspace scope is runtime-controlled."
            ),
            category="research",
            effect="read",
            requires_reading_context=False,
            requires_confirmation=False,
            args_model=SearchEvidenceLedgerArgs,
            result_model=SearchEvidenceLedgerToolData,
            executor=tools.search_evidence_ledger,
            planner_args_model=SearchEvidenceLedgerArgs,
            retry_policy="safe",
        ),
        typed_tool_definition(
            name="save_evidence_ledger",
            title="Save findings to Evidence Ledger",
            description=(
                "Persist deterministic Stage 18 cross-document findings as Claim-centered Evidence "
                "Ledger entries in the active Research Workspace. This is a durable write and "
                "requires explicit confirmation; the Agent controls only the research query."
            ),
            category="research",
            effect="write",
            requires_reading_context=False,
            requires_confirmation=True,
            args_model=SaveEvidenceLedgerArgs,
            result_model=SaveEvidenceLedgerToolData,
            executor=tools.save_evidence_ledger,
            planner_args_model=SaveEvidenceLedgerArgs,
            retry_policy="never",
        ),
    )


__all__ = [
    "EvidenceLedgerAgentTools",
    "SaveEvidenceLedgerArgs",
    "SearchEvidenceLedgerArgs",
    "build_evidence_ledger_tool_definitions",
]
