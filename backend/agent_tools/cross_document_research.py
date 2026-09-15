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
from backend.models.cross_document_research import CrossDocumentAnalysis
from backend.rag.citation_service import build_evidence_citations

_CROSS_DOCUMENT_TEXT_LIMIT = 1_600
_CROSS_DOCUMENT_QUERY_LIMIT = 4_000


class AnalyzeCrossDocumentResearchArgs(AgentToolModel):
    query: str = Field(min_length=1, max_length=_CROSS_DOCUMENT_QUERY_LIMIT)


class CrossDocumentResearchToolData(AgentToolModel):
    workspace_id: str = Field(default="", max_length=128)
    query: str = Field(default="", max_length=_CROSS_DOCUMENT_QUERY_LIMIT)
    document_count: int = Field(default=0, ge=0)
    agreement_count: int = Field(default=0, ge=0)
    disagreement_count: int = Field(default=0, ge=0)
    analysis: dict[str, Any] = Field(default_factory=dict)
    evidence: list[AgentEvidenceItem] = Field(default_factory=list)
    citations: list[AgentCitationRef] = Field(default_factory=list)


def _bounded(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text if len(text) <= limit else text[:limit].rstrip()


class CrossDocumentResearchAgentTool:
    """Agent boundary over deterministic cross-document structured analysis."""

    def __init__(
        self,
        *,
        cross_document_service: Any | None,
        research_memory_service: Any,
        research_note_service: Any,
    ) -> None:
        self._cross_document = cross_document_service
        self._memory = research_memory_service
        self._notes = research_note_service

    @staticmethod
    def _evidence_contexts(analysis: CrossDocumentAnalysis) -> dict[str, dict[str, Any]]:
        contexts: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "agreement_ids": set(),
                "disagreement_ids": set(),
                "score": 0.0,
            }
        )
        for agreement in analysis.agreements:
            for support in agreement.supports:
                for evidence_id in support.evidence_ids:
                    item = contexts[evidence_id]
                    item["agreement_ids"].add(agreement.cluster_id)
                    item["score"] = max(item["score"], float(support.confidence))
        for disagreement in analysis.disagreements:
            for alternative in disagreement.alternatives:
                for support in alternative.supports:
                    for evidence_id in support.evidence_ids:
                        item = contexts[evidence_id]
                        item["disagreement_ids"].add(disagreement.group_id)
                        item["score"] = max(item["score"], float(support.confidence))
        return contexts

    def analyze_cross_document_research(
        self,
        context: AgentToolInvocationContext,
        args: BaseModel,
    ) -> AgentToolExecutionResult:
        typed = cast(AnalyzeCrossDocumentResearchArgs, args)
        workspace_id = context.workspace_id.strip()
        if not workspace_id:
            return AgentToolExecutionResult(
                tool_name="analyze_cross_document_research",
                output_text="Cross-document research analysis requires an active Research Workspace.",
                effect="read",
                request_id=context.request_id,
                data={
                    "workspace_id": "",
                    "query": typed.query,
                    "document_count": 0,
                    "agreement_count": 0,
                    "disagreement_count": 0,
                    "analysis": {},
                    "evidence": [],
                    "citations": [],
                },
            )
        if self._cross_document is None:
            raise RuntimeError("Cross-document research analysis is unavailable.")

        analysis = self._cross_document.analyze(
            workspace_id=workspace_id,
            query=typed.query,
        )
        snapshot = self._memory.snapshot(workspace_id=workspace_id, limit=500)
        evidence_by_id = {item.evidence_id: item for item in snapshot.evidence}
        contexts = self._evidence_contexts(analysis)

        evidence: list[AgentEvidenceItem] = []
        for evidence_id, metadata in sorted(
            contexts.items(),
            key=lambda item: (float(item[1]["score"]), item[0]),
            reverse=True,
        ):
            source = evidence_by_id.get(evidence_id)
            if source is None:
                continue
            status = str(
                self._memory.source_status(
                    workspace_id=workspace_id,
                    note_id=source.note_id,
                )
                or "legacy_unknown"
            )
            if status not in {"fresh", "legacy_unknown"}:
                continue
            note = self._notes.get(source.note_id)
            if note is None:
                continue
            evidence.append(
                AgentEvidenceItem(
                    evidence_id=f"cross-document:{source.evidence_id}",
                    source_type="research_memory",
                    source_id=source.note_id,
                    title=_bounded(note.display_title, 1024),
                    resource_url=_bounded(getattr(note, "resource_url", ""), 4096),
                    location=_bounded(getattr(note, "section_heading", ""), 1024),
                    excerpt=_bounded(source.excerpt, _CROSS_DOCUMENT_TEXT_LIMIT),
                    score=max(0.0, min(1.0, float(metadata["score"]))),
                    metadata={
                        "workspace_id": workspace_id,
                        "note_id": source.note_id,
                        "claim_id": source.claim_id,
                        "structured_evidence_id": source.evidence_id,
                        "memory_source_status": status,
                        "agreement_cluster_ids": sorted(metadata["agreement_ids"]),
                        "disagreement_group_ids": sorted(metadata["disagreement_ids"]),
                        "source_verified": True,
                    },
                )
            )
        citations = build_evidence_citations(evidence)

        lines = [
            f"Cross-document analysis across {analysis.document_count} document source(s)."
        ]
        if analysis.agreements:
            lines.append("Agreements supported by multiple document sources:")
            for item in analysis.agreements[:8]:
                lines.append(
                    f"- {item.statement} ({len(item.document_ids)} documents, "
                    f"{len(item.supports)} supports)"
                )
        if analysis.disagreements:
            lines.append("Conservative cross-document disagreements:")
            for item in analysis.disagreements[:8]:
                alternatives = "; ".join(
                    f"{alternative.target_name} ({len(alternative.document_ids)} documents)"
                    for alternative in item.alternatives
                )
                lines.append(
                    f"- {item.subject_name} {item.predicate}: {alternatives}"
                )
        if not analysis.agreements and not analysis.disagreements:
            lines.append(
                "No deterministic cross-document agreement or disagreement was found for this query."
            )
        if analysis.document_count < 2:
            lines.append(
                "At least two distinct document sources are required for cross-document conclusions."
            )

        return AgentToolExecutionResult(
            tool_name="analyze_cross_document_research",
            output_text="\n".join(lines),
            effect="read",
            request_id=context.request_id,
            data={
                "workspace_id": workspace_id,
                "query": typed.query,
                "document_count": analysis.document_count,
                "agreement_count": analysis.agreement_count,
                "disagreement_count": analysis.disagreement_count,
                "analysis": analysis.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "citations": [item.model_dump(mode="json") for item in citations],
            },
        )


def build_cross_document_research_tool_definition(
    tool: CrossDocumentResearchAgentTool,
) -> TypedAgentToolDefinition:
    return typed_tool_definition(
        name="analyze_cross_document_research",
        title="Analyze research across documents",
        description=(
            "Compare reliable structured Claim/Evidence/Relation memory across distinct document "
            "sources in the active Research Workspace. Detect repeated exact propositions and "
            "conservative disagreements while preserving source evidence and citations. The runtime "
            "controls Workspace scope; the Agent controls only the research query."
        ),
        category="research",
        effect="read",
        requires_reading_context=False,
        requires_confirmation=False,
        args_model=AnalyzeCrossDocumentResearchArgs,
        result_model=CrossDocumentResearchToolData,
        executor=tool.analyze_cross_document_research,
        planner_args_model=AnalyzeCrossDocumentResearchArgs,
        retry_policy="safe",
    )


__all__ = [
    "AnalyzeCrossDocumentResearchArgs",
    "CrossDocumentResearchAgentTool",
    "CrossDocumentResearchToolData",
    "build_cross_document_research_tool_definition",
]
