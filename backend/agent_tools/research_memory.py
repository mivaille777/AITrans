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

_AGENT_MEMORY_TEXT_LIMIT = 1_200
_AGENT_MEMORY_RESULT_LIMIT = 20


class SearchResearchMemoryArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=8, ge=1, le=_AGENT_MEMORY_RESULT_LIMIT)


class SearchResearchMemoryPlannerArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=4_000)


class ResearchMemoryAgentSearchItem(AgentToolModel):
    kind: str = Field(max_length=32)
    item_id: str = Field(max_length=128)
    note_id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=1024)
    text: str = Field(max_length=_AGENT_MEMORY_TEXT_LIMIT)
    score: float = Field(ge=0.0)
    claim_id: str = Field(default="", max_length=128)
    entity_id: str = Field(default="", max_length=128)
    source_status: str = Field(default="legacy_unknown", max_length=32)
    groundable: bool = False
    conflicted: bool = False
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    conflict_group_ids: list[str] = Field(default_factory=list, max_length=32)
    grounded_evidence_ids: list[str] = Field(default_factory=list, max_length=32)


class ResearchMemoryAgentSearchData(AgentToolModel):
    workspace_id: str = Field(default="", max_length=128)
    query: str = Field(max_length=4_000)
    results: list[ResearchMemoryAgentSearchItem] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)
    grounded_result_count: int = Field(default=0, ge=0)
    fresh_result_count: int = Field(default=0, ge=0)
    legacy_unknown_result_count: int = Field(default=0, ge=0)
    stale_result_count: int = Field(default=0, ge=0)
    orphaned_result_count: int = Field(default=0, ge=0)
    detached_result_count: int = Field(default=0, ge=0)
    conflicted_result_count: int = Field(default=0, ge=0)
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)


def _bounded(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text if len(text) <= limit else text[:limit].rstrip()


class ResearchMemoryAgentTool:
    """Read-only Agent boundary over workspace-scoped structured research memory."""

    def __init__(
        self,
        *,
        research_memory_service: Any | None,
        research_note_service: Any,
    ) -> None:
        self._research_memory = research_memory_service
        self._research_notes = research_note_service

    @staticmethod
    def _evidence_ids_by_result(snapshot: Any, results: tuple[Any, ...]) -> dict[str, list[str]]:
        evidence_by_claim: dict[str, list[str]] = defaultdict(list)
        for evidence in snapshot.evidence:
            if evidence.claim_id:
                evidence_by_claim[evidence.claim_id].append(evidence.evidence_id)

        relation_claims_by_entity: dict[str, set[str]] = defaultdict(set)
        for relation in snapshot.relations:
            if not relation.claim_id:
                continue
            relation_claims_by_entity[relation.source_entity_id].add(relation.claim_id)
            relation_claims_by_entity[relation.target_entity_id].add(relation.claim_id)

        mapping: dict[str, list[str]] = {}
        for result in results:
            identifiers: list[str] = []
            if result.kind == "evidence":
                identifiers.append(result.item_id)
            elif result.kind in {"claim", "relation"} and result.claim_id:
                identifiers.extend(evidence_by_claim.get(result.claim_id, ()))
            elif result.kind == "entity" and result.entity_id:
                for claim_id in sorted(relation_claims_by_entity.get(result.entity_id, ())):
                    identifiers.extend(evidence_by_claim.get(claim_id, ()))
            mapping[result.item_id] = list(dict.fromkeys(identifiers))[:32]
        return mapping

    @staticmethod
    def _source_status(service: Any, *, workspace_id: str, note_id: str) -> str:
        getter = getattr(service, "source_status", None)
        if not callable(getter):
            return "legacy_unknown"
        return str(getter(workspace_id=workspace_id, note_id=note_id) or "legacy_unknown")

    @staticmethod
    def _empty_data(*, query: str) -> dict[str, Any]:
        return {
            "workspace_id": "",
            "query": query,
            "results": [],
            "count": 0,
            "grounded_result_count": 0,
            "fresh_result_count": 0,
            "legacy_unknown_result_count": 0,
            "stale_result_count": 0,
            "orphaned_result_count": 0,
            "detached_result_count": 0,
            "conflicted_result_count": 0,
            "evidence": [],
            "citations": [],
        }

    def search_research_memory(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(SearchResearchMemoryArgs, args)
        workspace_id = context.workspace_id.strip()
        service = self._research_memory
        if not workspace_id:
            return AgentToolExecutionResult(
                tool_name="search_research_memory",
                output_text="Structured research memory requires an active Research Workspace.",
                effect="read",
                request_id=context.request_id,
                data=self._empty_data(query=typed.query),
            )
        if service is None:
            raise RuntimeError("Structured research-memory search is unavailable.")

        reliability_by_result: dict[str, Any] = {}
        reliable_search = getattr(service, "search_reliable", None)
        if callable(reliable_search):
            reliable_results = tuple(
                reliable_search(
                    workspace_id=workspace_id,
                    query=typed.query,
                    limit=typed.top_k,
                )
            )
            results = tuple(item.result for item in reliable_results)
            reliability_by_result = {
                item.result.item_id: item.reliability for item in reliable_results
            }
        else:
            results = tuple(
                service.search(
                    workspace_id=workspace_id,
                    query=typed.query,
                    limit=typed.top_k,
                )
            )

        snapshot = service.snapshot(workspace_id=workspace_id, limit=500)
        evidence_ids_by_result = self._evidence_ids_by_result(snapshot, results)
        evidence_by_id = {item.evidence_id: item for item in snapshot.evidence}

        score_by_evidence: dict[str, float] = {}
        for result in results:
            for evidence_id in evidence_ids_by_result.get(result.item_id, ()):
                score_by_evidence[evidence_id] = max(
                    score_by_evidence.get(evidence_id, 0.0),
                    max(0.0, float(result.score)),
                )

        evidence: list[AgentEvidenceItem] = []
        available_public_evidence_ids: dict[str, str] = {}
        for evidence_id, score in sorted(
            score_by_evidence.items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        ):
            source = evidence_by_id.get(evidence_id)
            if source is None:
                continue
            source_status = self._source_status(
                service,
                workspace_id=workspace_id,
                note_id=source.note_id,
            )
            if source_status in {"stale", "orphaned", "detached"}:
                continue
            note = self._research_notes.get(source.note_id)
            if note is None:
                continue
            public_id = f"research-memory:{source.evidence_id}"
            available_public_evidence_ids[source.evidence_id] = public_id
            evidence.append(
                AgentEvidenceItem(
                    evidence_id=public_id,
                    source_type="research_memory",
                    source_id=source.note_id,
                    title=_bounded(note.display_title, 1024),
                    resource_url=_bounded(getattr(note, "resource_url", ""), 4096),
                    location=_bounded(getattr(note, "section_heading", ""), 1024),
                    excerpt=_bounded(source.excerpt, _AGENT_MEMORY_TEXT_LIMIT),
                    score=score,
                    metadata={
                        "workspace_id": workspace_id,
                        "note_id": source.note_id,
                        "claim_id": source.claim_id,
                        "structured_evidence_id": source.evidence_id,
                        "source_kind": _bounded(getattr(note, "source_kind", ""), 128),
                        "source_verified": True,
                        "memory_source_status": source_status,
                    },
                )
            )

        citations = build_evidence_citations(evidence)
        items: list[dict[str, Any]] = []
        grounded_result_count = 0
        status_counts: dict[str, int] = defaultdict(int)
        conflicted_result_count = 0
        for result in results:
            reliability = reliability_by_result.get(result.item_id)
            source_status = str(
                getattr(reliability, "source_status", "legacy_unknown") or "legacy_unknown"
            )
            conflicted = bool(getattr(reliability, "conflicted", False))
            groundable = bool(getattr(reliability, "groundable", False))
            reason_codes = list(getattr(reliability, "reason_codes", ()) or ())[:32]
            conflict_group_ids = list(
                getattr(reliability, "conflict_group_ids", ()) or ()
            )[:32]
            status_counts[source_status] += 1
            if conflicted:
                conflicted_result_count += 1

            raw_ids = evidence_ids_by_result.get(result.item_id, ())
            grounded_ids = [
                available_public_evidence_ids[evidence_id]
                for evidence_id in raw_ids
                if evidence_id in available_public_evidence_ids
            ]
            if grounded_ids:
                grounded_result_count += 1
                groundable = True
            else:
                groundable = False
            items.append(
                {
                    "kind": _bounded(result.kind, 32),
                    "item_id": _bounded(result.item_id, 128),
                    "note_id": _bounded(result.note_id, 128),
                    "title": _bounded(result.title, 1024),
                    "text": _bounded(result.text, _AGENT_MEMORY_TEXT_LIMIT),
                    "score": max(0.0, float(result.score)),
                    "claim_id": _bounded(result.claim_id, 128),
                    "entity_id": _bounded(result.entity_id, 128),
                    "source_status": _bounded(source_status, 32),
                    "groundable": groundable,
                    "conflicted": conflicted,
                    "reason_codes": [_bounded(item, 128) for item in reason_codes],
                    "conflict_group_ids": [
                        _bounded(item, 64) for item in conflict_group_ids
                    ],
                    "grounded_evidence_ids": grounded_ids[:32],
                }
            )

        if items:
            lines = []
            for item in items:
                flags = [item["source_status"]]
                if item["conflicted"]:
                    flags.append("conflict")
                if not item["groundable"]:
                    flags.append("not-groundable")
                lines.append(
                    f"- [{item['kind']} | {', '.join(flags)}] "
                    f"{item['title'] or item['item_id']}: {item['text']}"
                )
            output_text = "Structured research memory results:\n" + "\n".join(lines)
            if conflicted_result_count:
                output_text += (
                    "\nReliability warning: conflicting single-value structured relations are "
                    "present. Treat them as competing evidence rather than one settled fact."
                )
            if any(status_counts.get(name, 0) for name in ("stale", "orphaned", "detached")):
                output_text += (
                    "\nReliability warning: stale, orphaned, or Workspace-detached structured "
                    "hits are not eligible for grounded citations."
                )
        else:
            output_text = "No matching structured research memory found in the active Workspace."

        return AgentToolExecutionResult(
            tool_name="search_research_memory",
            output_text=output_text,
            effect="read",
            request_id=context.request_id,
            data={
                "workspace_id": workspace_id,
                "query": typed.query,
                "results": items,
                "count": len(items),
                "grounded_result_count": grounded_result_count,
                "fresh_result_count": status_counts.get("fresh", 0),
                "legacy_unknown_result_count": status_counts.get("legacy_unknown", 0),
                "stale_result_count": status_counts.get("stale", 0),
                "orphaned_result_count": status_counts.get("orphaned", 0),
                "detached_result_count": status_counts.get("detached", 0),
                "conflicted_result_count": conflicted_result_count,
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "citations": [item.model_dump(mode="json") for item in citations],
            },
        )


def build_research_memory_tool_definition(
    tool: ResearchMemoryAgentTool,
) -> TypedAgentToolDefinition:
    return typed_tool_definition(
        name="search_research_memory",
        title="Search structured research memory",
        description=(
            "Search Claim–Evidence–Entity–Relation memory inside the active Research Workspace. "
            "The runtime supplies the trusted Workspace; the Agent controls only the high-level query. "
            "Freshness, Workspace membership and structured-relation conflicts are evaluated "
            "deterministically by the runtime."
        ),
        category="research",
        effect="read",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=SearchResearchMemoryArgs,
        result_model=ResearchMemoryAgentSearchData,
        executor=tool.search_research_memory,
        planner_args_model=SearchResearchMemoryPlannerArgs,
        retry_policy="safe",
    )


__all__ = [
    "ResearchMemoryAgentSearchData",
    "ResearchMemoryAgentSearchItem",
    "ResearchMemoryAgentTool",
    "SearchResearchMemoryArgs",
    "SearchResearchMemoryPlannerArgs",
    "build_research_memory_tool_definition",
]
