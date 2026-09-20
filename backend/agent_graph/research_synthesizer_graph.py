from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.coordinator_memory import role_memory_projection
from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.models.agent_artifacts import (
    ComparisonArtifact,
    ComparisonCell,
    DocumentAnalysisArtifact,
    ResearchHypothesis,
    SourceCoverage,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus

_DIMENSIONS = ("methods", "datasets", "experiments", "limitations")


class ResearchSynthesisProvider(Protocol):
    def synthesize(
        self,
        *,
        objective: str,
        documents: tuple[DocumentAnalysisArtifact, ...],
        memory_context: tuple[Mapping[str, Any], ...],
    ) -> Mapping[str, Any]: ...


class ResearchSynthesizerState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    memory_context: list[dict[str, Any]]
    input_issues: list[dict[str, Any]]
    documents: list[DocumentAnalysisArtifact]
    draft: dict[str, Any]
    artifact: ComparisonArtifact
    result: TaskResult


class DeterministicResearchSynthesisProvider:
    def synthesize(
        self,
        *,
        objective: str,
        documents: tuple[DocumentAnalysisArtifact, ...],
        memory_context: tuple[Mapping[str, Any], ...],
    ) -> Mapping[str, Any]:
        del objective
        cells: list[dict[str, Any]] = []
        for document in documents:
            field_evidence = dict(document.content.get("field_evidence", {}) or {})
            for dimension in _DIMENSIONS:
                values = list(getattr(document, dimension))
                cells.append(
                    {
                        "dimension": dimension,
                        "source_label": document.document_id,
                        "value": "\n".join(values),
                        "conditions": (
                            "; ".join(document.datasets)
                            if dimension == "experiments"
                            else ""
                        ),
                        "evidence_ids": list(field_evidence.get(dimension, [])),
                        "unknown": not bool(values),
                    }
                )

        consensus: list[str] = []
        conflicts: list[str] = []
        for dimension in _DIMENSIONS:
            values = [
                cell["value"]
                for cell in cells
                if cell["dimension"] == dimension and cell["value"]
            ]
            if len(values) == len(documents) and len(set(values)) == 1 and values:
                consensus.append(f"All analyzed documents report the same {dimension}: {values[0]}")
            elif len(set(values)) > 1:
                conflicts.append(
                    f"The analyzed documents differ in {dimension}; compare each cell with its conditions."
                )
        return {
            "dimensions": list(_DIMENSIONS),
            "cells": cells,
            "consensus": consensus,
            "conflicts": conflicts,
            "supported_limitations": sorted(
                {item for document in documents for item in document.limitations}
            ),
            "research_directions": [],
            "research_hypotheses": [
                {
                    "statement": str(item["text"]),
                    "basis_ids": [str(item["item_id"])],
                    "status": "hypothesis",
                }
                for item in memory_context
                if str(item.get("kind", "")).casefold()
                in {"hypothesis", "research_direction"}
            ],
        }


def _artifact_id(task: TaskSpec, scope: ScopeContext) -> str:
    material = f"{scope.scope_ref}\0{task.task_id}\0{task.objective}".encode()
    return f"comparison:{hashlib.sha256(material).hexdigest()[:24]}"


def _bounded_memory_context(
    memory_snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Normalize an already-authorized frozen snapshot without treating it as evidence."""

    candidates: list[Any] = []
    candidates.extend(role_memory_projection(dict(memory_snapshot), "research"))
    for key in ("hypotheses", "items", "claims"):
        value = memory_snapshot.get(key, [])
        if isinstance(value, list | tuple):
            candidates.extend(value)
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates[:20], start=1):
        if not isinstance(raw, Mapping) or raw.get("authorized", True) is False:
            continue
        text = str(
            raw.get("text")
            or raw.get("content")
            or raw.get("summary")
            or raw.get("hypothesis")
            or ""
        ).strip()
        if not text:
            continue
        normalized.append(
            {
                "item_id": str(
                    raw.get("item_id")
                    or raw.get("claim_id")
                    or raw.get("id")
                    or f"memory-item-{index}"
                )[:256],
                "kind": str(raw.get("kind") or raw.get("claim_type") or "context")[
                    :128
                ],
                "text": text[:2000],
            }
        )
    return normalized


class ResearchSynthesizerGraph:
    def __init__(
        self,
        *,
        artifact_store: Any,
        provider: ResearchSynthesisProvider | None = None,
        evidence_review_service: Any | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._provider = provider or DeterministicResearchSynthesisProvider()
        self._reviews = evidence_review_service
        builder = StateGraph(ResearchSynthesizerState)
        builder.add_node("load_document_artifacts", self._load_document_artifacts)
        builder.add_node("load_authorized_memory", self._load_authorized_memory)
        builder.add_node("synthesize_comparison", self._synthesize_comparison)
        builder.add_node("verify_comparison", self._verify_comparison)
        builder.add_edge(START, "load_document_artifacts")
        builder.add_edge("load_document_artifacts", "load_authorized_memory")
        builder.add_edge("load_authorized_memory", "synthesize_comparison")
        builder.add_edge("synthesize_comparison", "verify_comparison")
        builder.add_edge("verify_comparison", END)
        self._compiled = builder.compile()

    @property
    def compiled_graph(self):
        return self._compiled

    def _load_document_artifacts(
        self, state: ResearchSynthesizerState
    ) -> dict[str, Any]:
        documents: list[DocumentAnalysisArtifact] = []
        issues: list[dict[str, Any]] = []
        allowed_documents = set(state["scope"].allowed_document_ids)
        for result in state["dependency_results"].values():
            for ref in result.artifact_refs:
                artifact = self._artifacts.get(ref.artifact_id, ref.version)
                if artifact is None:
                    issues.append(
                        VerificationIssue(
                            code="missing_input_artifact",
                            severity="error",
                            message="A declared input artifact is unavailable.",
                        ).model_dump(mode="json")
                    )
                    continue
                if artifact.content_hash != ref.content_hash:
                    issues.append(
                        VerificationIssue(
                            code="input_artifact_hash_mismatch",
                            severity="error",
                            message="An input artifact does not match its immutable reference.",
                        ).model_dump(mode="json")
                    )
                    continue
                if not isinstance(artifact, DocumentAnalysisArtifact):
                    issues.append(
                        VerificationIssue(
                            code="wrong_input_artifact_type",
                            severity="error",
                            message="Research synthesis only accepts document analysis artifacts.",
                        ).model_dump(mode="json")
                    )
                    continue
                if artifact.document_id not in allowed_documents:
                    issues.append(
                        VerificationIssue(
                            code="input_artifact_outside_scope",
                            severity="error",
                            message="A document artifact is outside the authoritative scope.",
                        ).model_dump(mode="json")
                    )
                    continue
                documents.append(artifact)
        documents.sort(key=lambda item: (item.document_id, item.artifact_id))
        return {"documents": documents, "input_issues": issues}

    def _load_authorized_memory(
        self, state: ResearchSynthesizerState
    ) -> dict[str, Any]:
        return {
            "memory_context": _bounded_memory_context(
                state.get("memory_snapshot", {})
            )
        }

    def _synthesize_comparison(
        self, state: ResearchSynthesizerState
    ) -> dict[str, Any]:
        draft = dict(
            self._provider.synthesize(
                objective=state["task"].objective,
                documents=tuple(state.get("documents", [])),
                memory_context=tuple(state.get("memory_context", [])),
            )
        )
        return {"draft": draft}

    def _verify_comparison(
        self, state: ResearchSynthesizerState
    ) -> dict[str, Any]:
        task = state["task"]
        scope = state["scope"]
        documents = list(state.get("documents", []))
        draft = dict(state.get("draft", {}))
        available_evidence = {
            ref.evidence_id for document in documents for ref in document.evidence_refs
        }
        issues = [
            VerificationIssue.model_validate(item)
            for item in state.get("input_issues", [])
        ]
        cells: list[ComparisonCell] = []
        source_labels = {document.document_id for document in documents}
        seen_cells: set[tuple[str, str]] = set()
        available_memory_ids = {
            str(item["item_id"]) for item in state.get("memory_context", [])
        }
        hypotheses: list[ResearchHypothesis] = []
        for raw in draft.get("research_hypotheses", []) or []:
            hypothesis = ResearchHypothesis.model_validate(raw)
            unknown_basis = set(hypothesis.basis_ids) - available_memory_ids
            if unknown_basis or not hypothesis.basis_ids:
                issues.append(
                    VerificationIssue(
                        code="unsupported_research_hypothesis",
                        severity="error",
                        message=(
                            "A research hypothesis requires an authorized memory basis."
                        ),
                        field="research_hypotheses",
                    )
                )
                hypothesis = hypothesis.model_copy(
                    update={
                        "basis_ids": [
                            item
                            for item in hypothesis.basis_ids
                            if item in available_memory_ids
                        ]
                    }
                )
            hypotheses.append(hypothesis)
        for raw in draft.get("cells", []) or []:
            cell = ComparisonCell.model_validate(raw)
            cell_key = (cell.dimension, cell.source_label)
            if cell.dimension not in _DIMENSIONS or cell.source_label not in source_labels:
                issues.append(
                    VerificationIssue(
                        code="comparison_cell_outside_inputs",
                        severity="error",
                        message=(
                            "A comparison cell must use a supported dimension and an "
                            "input document label."
                        ),
                        field=cell.dimension,
                    )
                )
                continue
            if cell_key in seen_cells:
                issues.append(
                    VerificationIssue(
                        code="duplicate_comparison_cell",
                        severity="error",
                        message="A comparison dimension/document pair appears more than once.",
                        field=cell.dimension,
                    )
                )
                continue
            seen_cells.add(cell_key)
            unknown_evidence = set(cell.evidence_ids) - available_evidence
            if unknown_evidence:
                issues.append(
                    VerificationIssue(
                        code="unknown_comparison_evidence",
                        severity="error",
                        message="A comparison cell references evidence outside its input artifacts.",
                        field=cell.dimension,
                    )
                )
                cell = cell.model_copy(
                    update={
                        "evidence_ids": [
                            item
                            for item in cell.evidence_ids
                            if item in available_evidence
                        ]
                    }
                )
            if not cell.unknown and (not cell.value or not cell.evidence_ids):
                issues.append(
                    VerificationIssue(
                        code="unsupported_comparison_cell",
                        severity="error",
                        message="A non-unknown comparison value requires evidence.",
                        field=cell.dimension,
                    )
                )
            cells.append(cell)

        expected_cells = {
            (dimension, document.document_id)
            for dimension in _DIMENSIONS
            for document in documents
        }
        for dimension, source_label in sorted(expected_cells - seen_cells):
            cells.append(
                ComparisonCell(
                    dimension=dimension,
                    source_label=source_label,
                    unknown=True,
                )
            )

        if len(documents) < 2:
            issues.append(
                VerificationIssue(
                    code="insufficient_document_artifacts",
                    severity="error",
                    message="Cross-document synthesis requires at least two document artifacts.",
                )
            )
        if any(document.verification_status is VerificationStatus.FAILED for document in documents):
            issues.append(
                VerificationIssue(
                    code="failed_input_artifact",
                    severity="error",
                    message="A failed document analysis cannot support a completed synthesis.",
                )
            )
        partial_input_ids = [
            document.document_id
            for document in documents
            if document.verification_status is not VerificationStatus.PASSED
            or not document.source_coverage.complete
        ]
        if partial_input_ids:
            issues.append(
                VerificationIssue(
                    code="partial_input_coverage",
                    severity="warning",
                    message=(
                        "One or more document analyses have partial verification or "
                        f"source coverage: {', '.join(partial_input_ids)}."
                    ),
                    field="source_coverage",
                )
            )
        unknown_count = sum(1 for cell in cells if cell.unknown)
        if unknown_count:
            issues.append(
                VerificationIssue(
                    code="comparison_gaps",
                    severity="warning",
                    message=f"{unknown_count} comparison cells remain unknown.",
                )
            )

        formal_review = any(
            term in task.objective.casefold()
            for term in ("related work", "literature review", "文献综述")
        )
        if formal_review:
            accepted_count = 0
            if self._reviews is not None and scope.workspace_id:
                snapshot = self._reviews.snapshot(
                    workspace_id=scope.workspace_id,
                    query=task.objective,
                    limit=100,
                )
                accepted_count = int(getattr(snapshot, "accepted_count", 0) or 0)
            if accepted_count <= 0:
                issues.append(
                    VerificationIssue(
                        code="review_gate_not_satisfied",
                        severity="error",
                        message="Formal literature synthesis requires accepted Stage20 evidence.",
                    )
                )

        has_error = any(issue.severity == "error" for issue in issues)
        status = VerificationStatus.FAILED if has_error and not cells else (
            VerificationStatus.PARTIAL
            if has_error or unknown_count or partial_input_ids
            else VerificationStatus.PASSED
        )
        report = VerificationReport(
            status=status,
            checked_fields=list(_DIMENSIONS),
            source_ids=[document.document_id for document in documents],
            citation_count=len(available_evidence),
            issues=issues,
        )
        artifact = ComparisonArtifact(
            artifact_id=_artifact_id(task, scope),
            producer_task_id=task.task_id,
            scope_ref=scope.scope_ref,
            dimensions=list(_DIMENSIONS),
            cells=cells,
            consensus=[str(item) for item in draft.get("consensus", []) or []],
            conflicts=[str(item) for item in draft.get("conflicts", []) or []],
            supported_limitations=[
                str(item) for item in draft.get("supported_limitations", []) or []
            ],
            research_directions=[
                str(item) for item in draft.get("research_directions", []) or []
            ],
            research_hypotheses=hypotheses,
            content={
                "input_artifact_ids": [document.artifact_id for document in documents],
                "formal_review_gate_required": formal_review,
                "memory_snapshot_ref": str(
                    state.get("memory_snapshot", {}).get("snapshot_id", "") or ""
                ),
                "memory_context_ids": [
                    item["item_id"] for item in state.get("memory_context", [])
                ],
            },
            evidence_refs=[
                ref for document in documents for ref in document.evidence_refs
            ],
            lineage=[document.ref() for document in documents],
            source_coverage=SourceCoverage(
                complete=bool(documents)
                and all(document.source_coverage.complete for document in documents),
                covered_refs=[document.document_id for document in documents],
                missing_refs=[
                    document.document_id
                    for document in documents
                    if not document.source_coverage.complete
                ],
            ),
            verification_status=status,
            verification_report=report,
        )
        stored = self._artifacts.put(artifact)
        task_status = (
            TaskStatus.SUCCEEDED
            if status is VerificationStatus.PASSED
            else TaskStatus.FAILED
            if status is VerificationStatus.FAILED
            else TaskStatus.PARTIAL
        )
        result = TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=task_status,
            artifact_refs=[stored.ref()],
            evidence_refs=list(stored.evidence_refs),
            coverage=(
                sum(1 for cell in cells if not cell.unknown) / len(cells)
                if cells
                else 0.0
            ),
            unmet_requirements=[issue.code for issue in issues],
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
        final = self._compiled.invoke(
            {
                "task": task,
                "scope": scope,
                "dependency_results": dict(dependency_results),
                "memory_snapshot": dict(memory_snapshot),
            }
        )
        artifact = final["artifact"]
        return SpecialistExecution(
            result=final["result"],
            output=artifact.model_dump(mode="json"),
            direct_delivery=True,
        )


__all__ = [
    "DeterministicResearchSynthesisProvider",
    "ResearchSynthesisProvider",
    "ResearchSynthesizerGraph",
    "ResearchSynthesizerState",
]
