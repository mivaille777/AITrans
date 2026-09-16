from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.knowledge.domain import AI_SUGGESTIBLE_RELATION_TYPES, KnowledgeItemType
from backend.models.agent_artifacts import (
    Artifact,
    ClaimRecord,
    KnowledgeDraftArtifact,
    KnowledgeItemDraft,
    NoteDraft,
    RelationProposal,
    SourceCoverage,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus

_QUESTION_RE = re.compile(r"[?？]\s*$")
_METHOD_TERMS = ("method", "model", "algorithm", "approach", "方法", "模型", "算法")
_DATASET_TERMS = ("dataset", "corpus", "benchmark", "数据集", "语料", "基准")


class KnowledgeCuratorProvider(Protocol):
    def curate(
        self,
        *,
        objective: str,
        source_artifacts: tuple[Artifact, ...],
        workspace_id: str,
    ) -> Mapping[str, Any]: ...


class KnowledgeCuratorState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    source_artifacts: list[Artifact]
    draft: dict[str, Any]
    artifact: KnowledgeDraftArtifact
    result: TaskResult


def _short_title(statement: str) -> str:
    compact = " ".join(str(statement).split())
    return compact[:120] if compact else "Untitled research insight"


def _classify(statement: str) -> tuple[str, str]:
    lowered = statement.casefold()
    if _QUESTION_RE.search(statement):
        return KnowledgeItemType.QUESTION.value, ""
    if any(term in lowered for term in _METHOD_TERMS):
        return KnowledgeItemType.CONCEPT.value, "method"
    if any(term in lowered for term in _DATASET_TERMS):
        return KnowledgeItemType.CONCEPT.value, "dataset"
    return KnowledgeItemType.INSIGHT.value, ""


class DeterministicKnowledgeCuratorProvider:
    """Conservative fallback: transform verified claims, never the whole answer."""

    def curate(
        self,
        *,
        objective: str,
        source_artifacts: tuple[Artifact, ...],
        workspace_id: str,
    ) -> Mapping[str, Any]:
        del objective, workspace_id
        notes: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for artifact in source_artifacts:
            evidence_by_id = {item.evidence_id: item for item in artifact.evidence_refs}
            for claim in artifact.claims:
                statement = " ".join(claim.statement.split())
                key = statement.casefold()
                if not statement or key in seen:
                    continue
                seen.add(key)
                item_type, subtype = _classify(statement)
                source_ids = sorted(
                    {
                        evidence_by_id[evidence_id].source_id
                        for evidence_id in claim.evidence_ids
                        if evidence_id in evidence_by_id
                    }
                )
                draft_id = f"item-{len(items) + 1}"
                items.append(
                    {
                        "draft_id": draft_id,
                        "item_type": item_type,
                        "subtype": subtype,
                        "title": _short_title(statement),
                        "summary": statement,
                        "ai_content": statement,
                        "source_ids": source_ids,
                    }
                )
                if source_ids and claim.evidence_ids:
                    notes.append(
                        {
                            "draft_id": f"note-{len(notes) + 1}",
                            "source_id": source_ids[0],
                            "source_quote": statement,
                            "ai_content": statement,
                            "resource_title": _short_title(statement),
                        }
                    )
                if len(items) >= 24:
                    break
            if len(items) >= 24:
                break
        return {"notes": notes, "items": items, "relation_proposals": []}


def _artifact_id(task: TaskSpec, scope: ScopeContext) -> str:
    material = f"{scope.scope_ref}\0{task.task_id}\0{task.objective}".encode()
    return f"knowledge-draft:{hashlib.sha256(material).hexdigest()[:24]}"


class KnowledgeCuratorGraph:
    def __init__(
        self,
        *,
        artifact_store: Any,
        knowledge_workspace: Any,
        provider: KnowledgeCuratorProvider | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._knowledge = knowledge_workspace
        self._provider = provider or DeterministicKnowledgeCuratorProvider()
        builder = StateGraph(KnowledgeCuratorState)
        builder.add_node("collect_artifacts", self._collect_artifacts)
        builder.add_node("prepare_drafts", self._prepare_drafts)
        builder.add_node("verify_drafts", self._verify_drafts)
        builder.add_edge(START, "collect_artifacts")
        builder.add_edge("collect_artifacts", "prepare_drafts")
        builder.add_edge("prepare_drafts", "verify_drafts")
        builder.add_edge("verify_drafts", END)
        self._compiled = builder.compile()

    @property
    def compiled_graph(self):
        return self._compiled

    def _collect_artifacts(self, state: KnowledgeCuratorState) -> dict[str, Any]:
        artifacts: list[Artifact] = []
        seen: set[tuple[str, int]] = set()
        for result in state.get("dependency_results", {}).values():
            for ref in result.artifact_refs:
                key = (ref.artifact_id, ref.version)
                if key in seen:
                    continue
                artifact = self._artifacts.get(ref.artifact_id, ref.version)
                if artifact is not None:
                    artifacts.append(artifact)
                    seen.add(key)
        return {"source_artifacts": artifacts}

    def _prepare_drafts(self, state: KnowledgeCuratorState) -> dict[str, Any]:
        scope = state["scope"]
        workspace_id = scope.workspace_id or scope.scope_id
        payload = dict(
            self._provider.curate(
                objective=state["task"].objective,
                source_artifacts=tuple(state.get("source_artifacts", [])),
                workspace_id=workspace_id,
            )
        )
        return {"draft": payload}

    def _verify_drafts(self, state: KnowledgeCuratorState) -> dict[str, Any]:
        task, scope = state["task"], state["scope"]
        workspace_id = scope.workspace_id or scope.scope_id
        source_artifacts = state.get("source_artifacts", [])
        evidence_ids = {
            item.evidence_id
            for artifact in source_artifacts
            for item in artifact.evidence_refs
        }
        available_source_ids = {
            item.source_id
            for artifact in source_artifacts
            for item in artifact.evidence_refs
        }
        allowed_sources = (
            set(scope.allowed_document_ids)
            | set(scope.allowed_note_ids)
            | set(scope.allowed_item_ids)
            | set(scope.explicit_current_source_refs)
        )
        if scope.mode.value == "unscoped_global":
            allowed_sources |= available_source_ids

        raw = state.get("draft", {})
        issues: list[VerificationIssue] = []
        notes: list[NoteDraft] = []
        items: list[KnowledgeItemDraft] = []
        proposals: list[RelationProposal] = []
        draft_ids: set[str] = set()

        for value in raw.get("notes", []) or []:
            try:
                draft = NoteDraft.model_validate(value)
            except ValueError as exc:
                issues.append(
                    VerificationIssue(
                        code="invalid_note_draft", severity="error", message=str(exc)
                    )
                )
                continue
            if draft.source_id not in allowed_sources:
                issues.append(
                    VerificationIssue(
                        code="source_out_of_scope",
                        severity="error",
                        message="Note source is outside the authoritative scope.",
                        field=draft.draft_id,
                    )
                )
                continue
            notes.append(draft)
            draft_ids.add(draft.draft_id)

        visible_items = [
            item
            for item in self._knowledge.list_items()
            if scope.mode.value == "unscoped_global"
            or item.item_id in set(scope.allowed_item_ids)
        ]
        for value in raw.get("items", []) or []:
            try:
                draft = KnowledgeItemDraft.model_validate(value)
            except ValueError as exc:
                issues.append(
                    VerificationIssue(
                        code="invalid_item_draft", severity="error", message=str(exc)
                    )
                )
                continue
            unknown_sources = set(draft.source_ids) - allowed_sources
            if unknown_sources:
                issues.append(
                    VerificationIssue(
                        code="source_out_of_scope",
                        severity="error",
                        message=f"Item sources are outside scope: {sorted(unknown_sources)}",
                        field=draft.draft_id,
                    )
                )
                continue
            duplicates = [
                item.item_id
                for item in visible_items
                if item.title.strip().casefold() == draft.title.strip().casefold()
            ]
            metadata = dict(draft.metadata)
            if draft.subtype:
                metadata["subtype"] = draft.subtype
            items.append(
                draft.model_copy(
                    update={
                        "duplicate_candidate_ids": sorted(
                            set(draft.duplicate_candidate_ids) | set(duplicates)
                        ),
                        "metadata": metadata,
                    }
                )
            )
            draft_ids.add(draft.draft_id)

        allowed_endpoints = draft_ids | set(scope.allowed_item_ids)
        raw_proposals = raw.get("relation_proposals", raw.get("relations", [])) or []
        for index, value in enumerate(raw_proposals, start=1):
            candidate = dict(value)
            candidate.setdefault("proposal_id", f"proposal-{index}")
            try:
                proposal = RelationProposal.model_validate(candidate)
            except ValueError as exc:
                issues.append(
                    VerificationIssue(
                        code="invalid_relation_proposal",
                        severity="error",
                        message=str(exc),
                    )
                )
                continue
            if proposal.relation_type not in AI_SUGGESTIBLE_RELATION_TYPES:
                issues.append(
                    VerificationIssue(
                        code="relation_type_not_allowed",
                        severity="error",
                        message="Relation type is not AI-suggestible.",
                        field=proposal.proposal_id,
                    )
                )
                continue
            endpoints = {
                proposal.source_draft_or_item_id,
                proposal.target_draft_or_item_id,
            }
            if len(endpoints) != 2 or not endpoints.issubset(allowed_endpoints):
                issues.append(
                    VerificationIssue(
                        code="invalid_relation_endpoint",
                        severity="error",
                        message="Relation endpoints are not both in the scoped candidate set.",
                        field=proposal.proposal_id,
                    )
                )
                continue
            if proposal.relation_type == "supports" and not proposal.evidence_ids:
                issues.append(
                    VerificationIssue(
                        code="unsupported_supports_relation",
                        severity="error",
                        message="A supports proposal requires explicit evidence.",
                        field=proposal.proposal_id,
                    )
                )
                continue
            if set(proposal.evidence_ids) - evidence_ids:
                issues.append(
                    VerificationIssue(
                        code="unknown_relation_evidence",
                        severity="error",
                        message="Relation proposal references unknown evidence.",
                        field=proposal.proposal_id,
                    )
                )
                continue
            proposals.append(proposal)

        if not workspace_id:
            issues.append(
                VerificationIssue(
                    code="workspace_required",
                    severity="error",
                    message="Knowledge curation requires an explicit workspace.",
                )
            )
        if not notes and not items:
            issues.append(
                VerificationIssue(
                    code="no_curatable_claims",
                    severity="warning",
                    message="No evidence-backed note or item candidates were produced.",
                )
            )
        status = VerificationStatus.PARTIAL if issues else VerificationStatus.PASSED
        artifact = KnowledgeDraftArtifact(
            artifact_id=_artifact_id(task, scope),
            producer_task_id=task.task_id,
            scope_ref=scope.scope_ref,
            workspace_id=workspace_id or "unresolved",
            notes=notes,
            items=items,
            relation_proposals=proposals,
            content={
                "source_artifact_refs": [
                    item.ref().model_dump(mode="json") for item in source_artifacts
                ],
                "approval_required": True,
            },
            claims=[
                    ClaimRecord(
                        claim_id=f"{task.task_id}:draft:{index}",
                        statement=item.ai_content or item.summary or item.title,
                    category="suggestion",
                    evidence_ids=[],
                )
                for index, item in enumerate(items, start=1)
            ],
            evidence_refs=[
                item for source in source_artifacts for item in source.evidence_refs
            ],
            source_coverage=SourceCoverage(
                complete=bool(source_artifacts),
                covered_refs=sorted(available_source_ids),
            ),
            verification_status=status,
            verification_report=VerificationReport(
                status=status,
                checked_fields=[
                    "scope",
                    "sources",
                    "duplicates",
                    "relation_endpoints",
                    "relation_evidence",
                ],
                source_ids=sorted(available_source_ids),
                citation_count=len(evidence_ids),
                issues=issues,
            ),
            warnings=[issue.code for issue in issues],
        )
        stored = self._artifacts.put(artifact)
        result = TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED
            if status is VerificationStatus.PASSED
            else TaskStatus.PARTIAL,
            artifact_refs=[stored.ref()],
            evidence_refs=list(stored.evidence_refs),
            coverage=1.0 if source_artifacts else 0.0,
            unmet_requirements=[
                issue.code for issue in issues if issue.severity == "error"
            ],
            warnings=[issue.code for issue in issues if issue.severity != "error"],
            source_versions=dict(scope.source_versions),
        )
        return {"artifact": stored, "result": result}

    def execute(
        self,
        *,
        task: TaskSpec,
        scope: ScopeContext,
        dependency_results: Mapping[str, TaskResult],
        memory_snapshot: Mapping[str, Any],
    ) -> SpecialistExecution:
        del memory_snapshot
        final = self._compiled.invoke(
            {
                "task": task,
                "scope": scope,
                "dependency_results": dict(dependency_results),
            }
        )
        artifact = final["artifact"]
        return SpecialistExecution(
            result=final["result"],
            output=artifact.model_dump(mode="json"),
            direct_delivery=True,
        )


__all__ = [
    "DeterministicKnowledgeCuratorProvider",
    "KnowledgeCuratorGraph",
    "KnowledgeCuratorProvider",
    "KnowledgeCuratorState",
]
