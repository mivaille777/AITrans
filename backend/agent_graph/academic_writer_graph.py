from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.ai.errors import AIError
from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.models.agent_artifacts import (
    Artifact,
    ArtifactKind,
    ClaimRecord,
    ComparisonArtifact,
    DocumentAnalysisArtifact,
    EvidenceRef,
    ManuscriptSectionArtifact,
    OutlineArtifact,
    OutlineSection,
    ReferenceRecord,
    RevisionArtifact,
    RevisionChange,
    SourceCoverage,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus

_FORMAL_REVIEW_TERMS = ("related work", "literature review", "文献综述", "相关工作")
_EXPERIMENT_TERMS = ("experiment", "results", "实验", "结果")


class AcademicWriterProvider(Protocol):
    def generate(
        self,
        *,
        expected_kind: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class AcademicWriterState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    dependency_results: dict[str, TaskResult]
    memory_snapshot: dict[str, Any]
    input_artifacts: list[Artifact]
    input_issues: list[dict[str, Any]]
    user_material: list[dict[str, str]]
    review_evidence: list[dict[str, Any]]
    draft: dict[str, Any]
    artifact: Artifact
    result: TaskResult


def _artifact_id(task: TaskSpec, scope: ScopeContext, kind: ArtifactKind) -> str:
    material = f"{scope.scope_ref}\0{task.task_id}\0{task.objective}\0{kind.value}".encode()
    return f"{kind.value}:{hashlib.sha256(material).hexdigest()[:24]}"


def _stable_id(prefix: str, value: str, index: int) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{prefix}-{index}-{digest}"


def _is_formal_review(objective: str) -> bool:
    lowered = objective.casefold()
    return any(term in lowered for term in _FORMAL_REVIEW_TERMS)


def _is_experiment_section(objective: str) -> bool:
    lowered = objective.casefold()
    return any(term in lowered for term in _EXPERIMENT_TERMS)


def _normalize_user_material(snapshot: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_items = snapshot.get("user_supplied", [])
    if not isinstance(raw_items, list | tuple):
        return []
    result: list[dict[str, str]] = []
    for index, raw in enumerate(raw_items[:32], start=1):
        if not isinstance(raw, Mapping):
            continue
        text = str(raw.get("text") or raw.get("summary") or "").strip()
        if not text:
            continue
        result.append(
            {
                "evidence_id": str(raw.get("evidence_id") or f"user-supplied-{index}")[:256],
                "source_id": str(raw.get("source_id") or raw.get("experiment_id") or "user")[:256],
                "text": text[:20_000],
            }
        )
    return result


def _compact_artifact(artifact: Artifact) -> dict[str, Any]:
    base = {
        "artifact_id": artifact.artifact_id,
        "version": artifact.version,
        "kind": artifact.kind.value,
        "verification_status": artifact.verification_status.value,
        "evidence_ids": [item.evidence_id for item in artifact.evidence_refs],
    }
    if isinstance(artifact, DocumentAnalysisArtifact):
        base.update(
            {
                "document_id": artifact.document_id,
                "research_questions": artifact.research_questions,
                "contributions": artifact.contributions,
                "methods": artifact.methods,
                "datasets": artifact.datasets,
                "experiments": artifact.experiments,
                "limitations": artifact.limitations,
            }
        )
    elif isinstance(artifact, ComparisonArtifact):
        base.update(
            {
                "cells": [item.model_dump(mode="json") for item in artifact.cells],
                "consensus": artifact.consensus,
                "conflicts": artifact.conflicts,
                "supported_limitations": artifact.supported_limitations,
            }
        )
    elif isinstance(artifact, ManuscriptSectionArtifact):
        base.update(
            {
                "section_id": artifact.section_id,
                "title": artifact.title,
                "markdown": artifact.markdown,
                "paragraph_ids": artifact.paragraph_ids,
            }
        )
    return base


class DeterministicAcademicWriterProvider:
    """Conservative fallback that structures only already supplied material."""

    def generate(
        self,
        *,
        expected_kind: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        objective = str(payload.get("objective", "") or "")
        artifacts = list(payload.get("artifacts", []) or [])
        user_material = list(payload.get("user_supplied", []) or [])
        if expected_kind == ArtifactKind.OUTLINE.value:
            sections = [
                ("introduction", "Introduction"),
                ("related-work", "Related Work"),
                ("methods", "Methods"),
                ("results", "Results"),
                ("discussion", "Discussion"),
            ]
            evidence_ids = sorted(
                {
                    str(item)
                    for artifact in artifacts
                    for item in artifact.get("evidence_ids", [])
                }
            )
            return {
                "title": objective[:1000] or "Research manuscript outline",
                "sections": [
                    {
                        "section_id": section_id,
                        "title": title,
                        "objective": f"Develop {title.lower()} from verified project evidence.",
                        "evidence_ids": evidence_ids,
                    }
                    for section_id, title in sections
                ],
                "missing_inputs": [],
            }

        if expected_kind == ArtifactKind.REVISION.value:
            base = next(
                (item for item in artifacts if item.get("kind") == "manuscript_section"),
                None,
            )
            return {
                "target_section_id": str((base or {}).get("section_id") or "unknown"),
                "base_version": int((base or {}).get("version") or 1),
                "allowed_paragraph_ids": list((base or {}).get("paragraph_ids", [])),
                "changes": [],
                "missing_inputs": [] if base else ["target_manuscript_section"],
            }

        paragraphs: list[dict[str, Any]] = []
        if _is_experiment_section(objective):
            for index, item in enumerate(user_material, start=1):
                paragraphs.append(
                    {
                        "paragraph_id": _stable_id("result", str(item["text"]), index),
                        "markdown": str(item["text"]),
                        "category": "user_supplied",
                        "evidence_ids": [str(item["evidence_id"])],
                    }
                )
        else:
            statements: list[tuple[str, list[str], str]] = []
            for artifact in artifacts:
                if artifact.get("kind") == "comparison":
                    for cell in artifact.get("cells", []):
                        value = str(cell.get("value", "") or "").strip()
                        if value:
                            statements.append(
                                (value, list(cell.get("evidence_ids", [])), "fact")
                            )
                elif artifact.get("kind") == "document_analysis":
                    for field in ("contributions", "methods", "limitations"):
                        for value in artifact.get(field, []):
                            evidence_ids = list(artifact.get("evidence_ids", []))
                            statements.append((str(value), evidence_ids, "fact"))
            for index, (statement, evidence_ids, category) in enumerate(
                statements[:8], start=1
            ):
                paragraphs.append(
                    {
                        "paragraph_id": _stable_id("paragraph", statement, index),
                        "markdown": statement,
                        "category": category,
                        "evidence_ids": evidence_ids,
                    }
                )
        return {
            "section_id": "results" if _is_experiment_section(objective) else "draft",
            "title": objective[:1000] or "Draft section",
            "paragraphs": paragraphs,
            "missing_inputs": [] if paragraphs else [
                "user_supplied_experiment_results"
                if _is_experiment_section(objective)
                else "verified_research_artifacts"
            ],
        }


class FallbackAcademicWriterProvider:
    def __init__(self, primary: Any | None, fallback: AcademicWriterProvider | None = None) -> None:
        self._primary = primary
        self._fallback = fallback or DeterministicAcademicWriterProvider()

    def generate(self, *, expected_kind: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._primary is not None:
            try:
                return self._primary.generate(expected_kind=expected_kind, payload=payload)
            except (AIError, ValueError, TypeError):
                pass
        return self._fallback.generate(expected_kind=expected_kind, payload=payload)


class AcademicWriterGraph:
    def __init__(
        self,
        *,
        artifact_store: Any,
        provider: AcademicWriterProvider | None = None,
        literature_synthesis_service: Any | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._provider = provider or DeterministicAcademicWriterProvider()
        self._literature = literature_synthesis_service
        builder = StateGraph(AcademicWriterState)
        builder.add_node("load_writing_inputs", self._load_inputs)
        builder.add_node("generate_writing_draft", self._generate_draft)
        builder.add_node("verify_writing_artifact", self._verify)
        builder.add_edge(START, "load_writing_inputs")
        builder.add_edge("load_writing_inputs", "generate_writing_draft")
        builder.add_edge("generate_writing_draft", "verify_writing_artifact")
        builder.add_edge("verify_writing_artifact", END)
        self._compiled = builder.compile()

    @property
    def compiled_graph(self):
        return self._compiled

    def _load_inputs(self, state: AcademicWriterState) -> dict[str, Any]:
        inputs: list[Artifact] = []
        issues: list[dict[str, Any]] = []
        for result in state["dependency_results"].values():
            for ref in result.artifact_refs:
                artifact = self._artifacts.get(ref.artifact_id, ref.version)
                if artifact is None or artifact.content_hash != ref.content_hash:
                    issues.append(
                        VerificationIssue(
                            code="invalid_writing_input_ref",
                            severity="error",
                            message="A writing input artifact is missing or hash-mismatched.",
                        ).model_dump(mode="json")
                    )
                    continue
                if artifact.scope_ref != state["scope"].scope_ref:
                    issues.append(
                        VerificationIssue(
                            code="writing_input_scope_mismatch",
                            severity="error",
                            message="A writing input artifact is outside the authoritative scope.",
                        ).model_dump(mode="json")
                    )
                    continue
                inputs.append(artifact)
        return {
            "input_artifacts": inputs,
            "input_issues": issues,
            "user_material": _normalize_user_material(state.get("memory_snapshot", {})),
        }

    def _review_draft(self, state: AcademicWriterState) -> dict[str, Any]:
        scope = state["scope"]
        if self._literature is None or not scope.workspace_id:
            return {
                "draft": {
                    "section_id": "related-work",
                    "title": "Related Work",
                    "paragraphs": [],
                    "missing_inputs": ["accepted_stage20_evidence"],
                    "review_status": "unavailable",
                },
                "review_evidence": [],
            }
        response = self._literature.generate(
            workspace_id=scope.workspace_id,
            query=state["task"].objective,
            limit=100,
        )
        evidence: list[dict[str, Any]] = []
        evidence_ids: list[str] = []
        for item in (*response.plan.consensus, *response.plan.disagreements):
            for evidence_id in item.evidence_ids:
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
                    evidence.append(
                        EvidenceRef(
                            evidence_id=evidence_id,
                            source_id=(item.document_ids[0] if item.document_ids else "review-ledger"),
                            source_type="review_ledger",
                        ).model_dump(mode="json")
                    )
        paragraphs = []
        if response.output_text.strip() and response.included_count > 0:
            paragraphs.append(
                {
                    "paragraph_id": _stable_id("related-work", response.output_text, 1),
                    "markdown": response.output_text,
                    "category": "fact",
                    "evidence_ids": evidence_ids,
                }
            )
        return {
            "draft": {
                "section_id": "related-work",
                "title": "Related Work",
                "paragraphs": paragraphs,
                "missing_inputs": [] if paragraphs else ["accepted_stage20_evidence"],
                "review_status": response.status,
                "review_prompt_id": response.prompt_id,
            },
            "review_evidence": evidence,
        }

    def _generate_draft(self, state: AcademicWriterState) -> dict[str, Any]:
        task = state["task"]
        if (
            task.expected_output_kind is ArtifactKind.MANUSCRIPT_SECTION
            and _is_formal_review(task.objective)
        ):
            return self._review_draft(state)
        payload = {
            "objective": task.objective,
            "artifacts": [
                _compact_artifact(item) for item in state.get("input_artifacts", [])
            ],
            "user_supplied": list(state.get("user_material", [])),
            "allowed_evidence_ids": sorted(
                {
                    ref.evidence_id
                    for artifact in state.get("input_artifacts", [])
                    for ref in artifact.evidence_refs
                }
                | {
                    item["evidence_id"] for item in state.get("user_material", [])
                }
            ),
        }
        if (
            task.expected_output_kind is ArtifactKind.MANUSCRIPT_SECTION
            and _is_experiment_section(task.objective)
            and not state.get("user_material")
        ):
            draft = DeterministicAcademicWriterProvider().generate(
                expected_kind=task.expected_output_kind.value,
                payload=payload,
            )
        else:
            draft = self._provider.generate(
                expected_kind=task.expected_output_kind.value,
                payload=payload,
            )
        return {"draft": dict(draft), "review_evidence": []}

    @staticmethod
    def _references(
        artifacts: list[Artifact], evidence_refs: list[EvidenceRef]
    ) -> list[ReferenceRecord]:
        metadata: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            raw = artifact.content.get("source_metadata", {})
            if isinstance(raw, Mapping):
                for source_id, value in raw.items():
                    if isinstance(value, Mapping):
                        metadata[str(source_id)] = dict(value)
        grouped: dict[str, list[str]] = {}
        for ref in evidence_refs:
            if ref.source_type == "user_supplied":
                continue
            grouped.setdefault(ref.source_id, []).append(ref.evidence_id)
        references: list[ReferenceRecord] = []
        for source_id, evidence_ids in sorted(grouped.items()):
            source = metadata.get(source_id, {})
            authors = [str(item) for item in source.get("authors", []) if str(item).strip()]
            title = str(source.get("title", "") or "").strip()
            year = str(source.get("year", "") or "").strip()
            doi = str(source.get("doi", "") or "").strip()
            references.append(
                ReferenceRecord(
                    source_id=source_id,
                    title=title,
                    authors=authors,
                    year=year,
                    doi=doi,
                    evidence_ids=sorted(set(evidence_ids)),
                    missing_fields=[
                        field
                        for field, value in (
                            ("title", title),
                            ("authors", authors),
                            ("year", year),
                            ("doi", doi),
                        )
                        if not value
                    ],
                )
            )
        return references

    def _verify(self, state: AcademicWriterState) -> dict[str, Any]:
        task = state["task"]
        scope = state["scope"]
        draft = dict(state.get("draft", {}))
        input_artifacts = list(state.get("input_artifacts", []))
        issues = [
            VerificationIssue.model_validate(item)
            for item in state.get("input_issues", [])
        ]
        evidence_refs = [
            ref for artifact in input_artifacts for ref in artifact.evidence_refs
        ] + [EvidenceRef.model_validate(item) for item in state.get("review_evidence", [])]
        for item in state.get("user_material", []):
            evidence_refs.append(
                EvidenceRef(
                    evidence_id=item["evidence_id"],
                    source_id=item["source_id"],
                    source_type="user_supplied",
                )
            )
        evidence_by_id = {item.evidence_id: item for item in evidence_refs}
        kind = task.expected_output_kind
        references = self._references(input_artifacts, list(evidence_by_id.values()))
        missing_inputs = [str(item) for item in draft.get("missing_inputs", []) or []]

        if kind is ArtifactKind.OUTLINE:
            sections: list[OutlineSection] = []
            for raw in draft.get("sections", []) or []:
                section = OutlineSection.model_validate(raw)
                unknown = set(section.evidence_ids) - set(evidence_by_id)
                if unknown:
                    issues.append(
                        VerificationIssue(
                            code="unknown_outline_evidence",
                            severity="error",
                            message="Outline section references evidence outside its inputs.",
                            field=section.section_id,
                        )
                    )
                    section = section.model_copy(
                        update={
                            "evidence_ids": [
                                item for item in section.evidence_ids if item in evidence_by_id
                            ]
                        }
                    )
                sections.append(section)
            if not sections:
                missing_inputs.append("outline_sections")
            status = (
                VerificationStatus.PARTIAL
                if missing_inputs or any(item.severity == "error" for item in issues)
                else VerificationStatus.PASSED
            )
            artifact: Artifact = OutlineArtifact(
                artifact_id=_artifact_id(task, scope, kind),
                producer_task_id=task.task_id,
                scope_ref=scope.scope_ref,
                title=str(draft.get("title", task.objective))[:1000],
                writing_goal=task.objective,
                sections=sections,
                references=references,
                missing_inputs=sorted(set(missing_inputs)),
                content={"draft_only": True, "applied": False},
                evidence_refs=list(evidence_by_id.values()),
                lineage=[item.ref() for item in input_artifacts],
                source_coverage=SourceCoverage(
                    complete=bool(input_artifacts)
                    and all(item.source_coverage.complete for item in input_artifacts),
                    covered_refs=[item.artifact_id for item in input_artifacts],
                ),
                verification_status=status,
                verification_report=VerificationReport(
                    status=status,
                    checked_fields=["sections", "evidence_ids", "references"],
                    source_ids=sorted({item.source_id for item in evidence_by_id.values()}),
                    citation_count=sum(len(item.evidence_ids) for item in sections),
                    issues=issues,
                ),
            )
        elif kind is ArtifactKind.REVISION:
            changes = [
                RevisionChange.model_validate(item)
                for item in draft.get("changes", []) or []
            ]
            target = str(draft.get("target_section_id", "") or "").strip()
            if not target:
                target = "unknown"
                missing_inputs.append("target_manuscript_section")
            allowed = [str(item) for item in draft.get("allowed_paragraph_ids", []) or []]
            if any(item.paragraph_id not in set(allowed) for item in changes):
                issues.append(
                    VerificationIssue(
                        code="revision_outside_allowed_paragraphs",
                        severity="error",
                        message="A revision changes a paragraph outside the authorized range.",
                    )
                )
            status = (
                VerificationStatus.PARTIAL
                if missing_inputs or not changes or any(item.severity == "error" for item in issues)
                else VerificationStatus.PASSED
            )
            artifact = RevisionArtifact(
                artifact_id=_artifact_id(task, scope, kind),
                producer_task_id=task.task_id,
                scope_ref=scope.scope_ref,
                target_section_id=target,
                base_version=max(1, int(draft.get("base_version", 1) or 1)),
                allowed_paragraph_ids=allowed,
                changes=changes,
                content={
                    "draft_only": True,
                    "applied": False,
                    "missing_inputs": sorted(set(missing_inputs)),
                },
                evidence_refs=list(evidence_by_id.values()),
                lineage=[item.ref() for item in input_artifacts],
                verification_status=status,
                verification_report=VerificationReport(
                    status=status,
                    checked_fields=["target_section", "allowed_paragraphs", "before_hash"],
                    source_ids=sorted({item.source_id for item in evidence_by_id.values()}),
                    citation_count=sum(len(item.evidence_ids) for item in changes),
                    issues=issues,
                ),
            )
        else:
            paragraphs: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            experiment = _is_experiment_section(task.objective)
            user_evidence = {item["evidence_id"] for item in state.get("user_material", [])}
            for index, raw in enumerate(draft.get("paragraphs", []) or [], start=1):
                paragraph_id = str(raw.get("paragraph_id") or "").strip() or _stable_id(
                    "paragraph", str(raw.get("markdown", "")), index
                )
                if paragraph_id in seen_ids:
                    issues.append(
                        VerificationIssue(
                            code="duplicate_paragraph_id",
                            severity="error",
                            message="Paragraph IDs must be unique.",
                            field=paragraph_id,
                        )
                    )
                    continue
                seen_ids.add(paragraph_id)
                markdown = str(raw.get("markdown", "") or "").strip()
                category = str(raw.get("category", "fact") or "fact")
                if category not in {"fact", "interpretation", "suggestion", "user_supplied"}:
                    category = "suggestion"
                evidence_ids = [
                    str(item) for item in raw.get("evidence_ids", []) or [] if str(item)
                ]
                unknown = set(evidence_ids) - set(evidence_by_id)
                if unknown:
                    issues.append(
                        VerificationIssue(
                            code="unknown_paragraph_evidence",
                            severity="error",
                            message="A paragraph references evidence outside the writer inputs.",
                            field=paragraph_id,
                        )
                    )
                    evidence_ids = [item for item in evidence_ids if item in evidence_by_id]
                if category == "fact" and not evidence_ids:
                    issues.append(
                        VerificationIssue(
                            code="unsupported_factual_paragraph",
                            severity="error",
                            message="A factual paragraph requires source evidence.",
                            field=paragraph_id,
                        )
                    )
                if category == "user_supplied" and (
                    not evidence_ids or not set(evidence_ids).issubset(user_evidence)
                ):
                    issues.append(
                        VerificationIssue(
                            code="user_supplied_category_without_user_source",
                            severity="error",
                            message=(
                                "A user-supplied paragraph must link only to explicit "
                                "user-supplied evidence."
                            ),
                            field=paragraph_id,
                        )
                    )
                if experiment and category in {"fact", "user_supplied"} and (
                    not evidence_ids or not set(evidence_ids).issubset(user_evidence)
                ):
                    issues.append(
                        VerificationIssue(
                            code="experiment_result_not_user_supplied",
                            severity="error",
                            message="Experiment results require explicit user-supplied evidence.",
                            field=paragraph_id,
                        )
                    )
                if markdown:
                    paragraphs.append(
                        {
                            "paragraph_id": paragraph_id,
                            "markdown": markdown,
                            "category": category,
                            "evidence_ids": evidence_ids,
                        }
                    )
            if not paragraphs:
                placeholder = (
                    "[Missing user-supplied experiment results]"
                    if experiment
                    else "[Missing verified research material]"
                )
                paragraphs.append(
                    {
                        "paragraph_id": _stable_id("placeholder", placeholder, 1),
                        "markdown": placeholder,
                        "category": "suggestion",
                        "evidence_ids": [],
                    }
                )
                missing_inputs.append(
                    "user_supplied_experiment_results"
                    if experiment
                    else "verified_research_artifacts"
                )
            has_error = any(item.severity == "error" for item in issues)
            status = (
                VerificationStatus.PARTIAL
                if missing_inputs or has_error
                else VerificationStatus.PASSED
            )
            markdown = "\n\n".join(item["markdown"] for item in paragraphs)
            claims = [
                ClaimRecord(
                    claim_id=f"{task.task_id}:{item['paragraph_id']}",
                    statement=item["markdown"],
                    category=item["category"],
                    evidence_ids=item["evidence_ids"],
                )
                for item in paragraphs
            ]
            artifact = ManuscriptSectionArtifact(
                artifact_id=_artifact_id(task, scope, kind),
                producer_task_id=task.task_id,
                scope_ref=scope.scope_ref,
                section_id=str(draft.get("section_id", "draft") or "draft")[:256],
                title=str(draft.get("title", task.objective) or task.objective)[:1000],
                markdown=markdown,
                paragraph_ids=[item["paragraph_id"] for item in paragraphs],
                claim_source_map={
                    item["paragraph_id"]: item["evidence_ids"] for item in paragraphs
                },
                references=references,
                missing_inputs=sorted(set(missing_inputs)),
                content={
                    "draft_only": True,
                    "applied": False,
                    "review_status": str(draft.get("review_status", "") or ""),
                    "review_prompt_id": str(draft.get("review_prompt_id", "") or ""),
                    "paragraph_categories": {
                        item["paragraph_id"]: item["category"] for item in paragraphs
                    },
                },
                claims=claims,
                evidence_refs=list(evidence_by_id.values()),
                lineage=[item.ref() for item in input_artifacts],
                source_coverage=SourceCoverage(
                    complete=(
                        bool(state.get("review_evidence"))
                        if _is_formal_review(task.objective)
                        else bool(input_artifacts)
                        and all(item.source_coverage.complete for item in input_artifacts)
                    ),
                    covered_refs=[item.artifact_id for item in input_artifacts],
                ),
                verification_status=status,
                verification_report=VerificationReport(
                    status=status,
                    checked_fields=[
                        "paragraph_ids",
                        "claim_source_map",
                        "experiment_source_policy",
                        "references",
                    ],
                    source_ids=sorted({item.source_id for item in evidence_by_id.values()}),
                    citation_count=sum(len(item["evidence_ids"]) for item in paragraphs),
                    issues=issues,
                ),
            )

        stored = self._artifacts.put(artifact)
        task_status = (
            TaskStatus.SUCCEEDED
            if stored.verification_status is VerificationStatus.PASSED
            else TaskStatus.PARTIAL
        )
        result = TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=task_status,
            artifact_refs=[stored.ref()],
            evidence_refs=list(stored.evidence_refs),
            coverage=(1.0 if task_status is TaskStatus.SUCCEEDED else 0.5),
            unmet_requirements=sorted(
                set(missing_inputs)
                | {item.code for item in issues if item.severity == "error"}
            ),
            warnings=[item.code for item in issues if item.severity != "error"],
            error_code=(
                "writer_verification_failed"
                if any(item.severity == "error" for item in issues)
                else ""
            ),
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
    "AcademicWriterGraph",
    "AcademicWriterProvider",
    "AcademicWriterState",
    "DeterministicAcademicWriterProvider",
    "FallbackAcademicWriterProvider",
]
