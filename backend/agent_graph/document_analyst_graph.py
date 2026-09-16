from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agent_core.orchestration.runtime_budget import reserve_runtime_resource
from backend.agent_core.orchestration.serial_executor import SpecialistExecution
from backend.models.agent_artifacts import (
    ClaimRecord,
    DocumentAnalysisArtifact,
    SourceCoverage,
    VerificationIssue,
    VerificationReport,
    VerificationStatus,
)
from backend.models.agent_evidence import EvidencePacket
from backend.models.agent_tasks import ScopeContext, TaskResult, TaskSpec, TaskStatus

_FIELD_TERMS = {
    "research_questions": ("research question", "objective", "aim", "研究问题", "目标"),
    "contributions": ("contribution", "propose", "introduce", "贡献", "提出"),
    "methods": ("method", "model", "algorithm", "approach", "方法", "模型", "算法"),
    "datasets": ("dataset", "corpus", "benchmark", "数据集", "语料"),
    "experiments": ("experiment", "accuracy", "result", "table", "实验", "准确率", "结果"),
    "limitations": ("limitation", "future work", "weakness", "局限", "不足"),
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


def _matches_field(field: str, sentence: str) -> bool:
    lowered = sentence.casefold()
    if not any(term in lowered for term in _FIELD_TERMS[field]):
        return False
    if field == "experiments":
        describes_dataset_only = any(
            term in lowered for term in _FIELD_TERMS["datasets"]
        ) and not any(
            term in lowered
            for term in ("accuracy", "result", "table", "score", "metric", "准确率", "结果")
        )
        if describes_dataset_only:
            return False
    return True


class DocumentAnalysisProvider(Protocol):
    def analyze(
        self,
        *,
        objective: str,
        document_ids: list[str],
        evidence: tuple[EvidencePacket, ...],
    ) -> Mapping[str, Any]: ...


class DocumentAnalystState(TypedDict, total=False):
    task: TaskSpec
    scope: ScopeContext
    document_ids: list[str]
    queries: list[str]
    evidence: list[EvidencePacket]
    draft: dict[str, Any]
    artifact: DocumentAnalysisArtifact
    result: TaskResult


class DeterministicDocumentAnalysisProvider:
    """Conservative local fallback that only extracts evidence-bearing sentences."""

    def analyze(
        self,
        *,
        objective: str,
        document_ids: list[str],
        evidence: tuple[EvidencePacket, ...],
    ) -> Mapping[str, Any]:
        del objective, document_ids
        fields: dict[str, list[str]] = {name: [] for name in _FIELD_TERMS}
        field_evidence: dict[str, list[str]] = {name: [] for name in _FIELD_TERMS}
        for packet in evidence:
            sentences = [
                sentence.strip()
                for sentence in _SENTENCE_SPLIT.split(packet.text)
                if sentence.strip()
            ] or ([packet.text.strip()] if packet.text.strip() else [])
            for field in _FIELD_TERMS:
                for sentence in sentences:
                    if _matches_field(field, sentence):
                        if sentence not in fields[field]:
                            fields[field].append(sentence[:4000])
                        evidence_id = packet.evidence_ref.evidence_id
                        if evidence_id not in field_evidence[field]:
                            field_evidence[field].append(evidence_id)
                        break
        return {
            **fields,
            "open_questions": [],
            "field_evidence": field_evidence,
            "coverage_complete": False,
        }


def _artifact_id(task: TaskSpec, scope: ScopeContext) -> str:
    material = f"{scope.scope_ref}\0{task.task_id}\0{task.objective}".encode()
    return f"document-analysis:{hashlib.sha256(material).hexdigest()[:24]}"


class DocumentAnalystGraph:
    def __init__(
        self,
        *,
        evidence_service: Any,
        artifact_store: Any,
        provider: DocumentAnalysisProvider | None = None,
        max_retrieval_queries: int = 3,
        evidence_per_query: int = 6,
    ) -> None:
        self._evidence = evidence_service
        self._artifacts = artifact_store
        self._provider = provider or DeterministicDocumentAnalysisProvider()
        self._max_queries = max(1, min(3, int(max_retrieval_queries)))
        self._evidence_per_query = max(1, min(12, int(evidence_per_query)))
        builder = StateGraph(DocumentAnalystState)
        builder.add_node("plan_coverage", self._plan_coverage)
        builder.add_node("retrieve_evidence", self._retrieve_evidence)
        builder.add_node("analyze_document", self._analyze_document)
        builder.add_node("verify_artifact", self._verify_artifact)
        builder.add_edge(START, "plan_coverage")
        builder.add_edge("plan_coverage", "retrieve_evidence")
        builder.add_edge("retrieve_evidence", "analyze_document")
        builder.add_edge("analyze_document", "verify_artifact")
        builder.add_edge("verify_artifact", END)
        self._compiled = builder.compile()

    @property
    def compiled_graph(self):
        return self._compiled

    def _plan_coverage(self, state: DocumentAnalystState) -> dict[str, Any]:
        task = state["task"]
        scope = state["scope"]
        document_ids = list(task.target_source_ids or scope.allowed_document_ids)
        queries = [
            task.objective,
            f"{task.objective} methods datasets experiments results",
            f"{task.objective} limitations future work",
        ][: self._max_queries]
        return {"document_ids": document_ids, "queries": queries}

    def _retrieve_evidence(self, state: DocumentAnalystState) -> dict[str, Any]:
        scope = state["scope"].model_copy(
            update={"allowed_document_ids": list(state["document_ids"])}
        )
        packets: dict[str, EvidencePacket] = {}
        for query in state["queries"]:
            reserve_runtime_resource("retrievals")
            reserve_runtime_resource("tool_calls")
            for packet in self._evidence.retrieve_packets(
                query=query,
                scope=scope,
                limit=self._evidence_per_query,
            ):
                if packet.evidence_ref.source_id not in set(state["document_ids"]):
                    continue
                packets[packet.evidence_ref.evidence_id] = packet
        return {"evidence": list(packets.values())}

    def _analyze_document(self, state: DocumentAnalystState) -> dict[str, Any]:
        draft = dict(
            self._provider.analyze(
                objective=state["task"].objective,
                document_ids=list(state["document_ids"]),
                evidence=tuple(state.get("evidence", [])),
            )
        )
        return {"draft": draft}

    def _verify_artifact(self, state: DocumentAnalystState) -> dict[str, Any]:
        task = state["task"]
        scope = state["scope"]
        packets = list(state.get("evidence", []))
        draft = dict(state.get("draft", {}))
        available_evidence = {
            packet.evidence_ref.evidence_id for packet in packets
        }
        fields = [*_FIELD_TERMS, "open_questions"]
        field_evidence = {
            str(field): [
                str(item)
                for item in values
                if str(item) in available_evidence
            ]
            for field, values in dict(draft.get("field_evidence", {}) or {}).items()
        }
        issues: list[VerificationIssue] = []
        claims: list[ClaimRecord] = []
        normalized: dict[str, list[str]] = {}
        for field in fields:
            values = [
                str(value).strip()
                for value in draft.get(field, []) or []
                if str(value).strip()
            ]
            normalized[field] = values
            evidence_ids = field_evidence.get(field, [])
            if values and not evidence_ids:
                issues.append(
                    VerificationIssue(
                        code="unsupported_field",
                        severity="error",
                        message=f"{field} has content without an evidence reference.",
                        field=field,
                    )
                )
            for index, statement in enumerate(values, start=1):
                claims.append(
                    ClaimRecord(
                        claim_id=f"{task.task_id}:{field}:{index}",
                        statement=statement,
                        evidence_ids=list(evidence_ids),
                    )
                )

        visited_documents = sorted(
            {packet.evidence_ref.source_id for packet in packets}
        )
        unavailable_documents = sorted(
            set(state["document_ids"]) - set(visited_documents)
        )
        requested_refs = [
            {
                "document_id": document_id,
                "source_version": scope.source_versions.get(document_id, ""),
                "section_path": [],
                "page_number": None,
                "element_id": "",
                "table_id": "",
                "image_id": "",
            }
            for document_id in state["document_ids"]
        ]
        visited_locations = [
            {
                "document_id": packet.evidence_ref.source_id,
                "source_version": packet.evidence_ref.source_version,
                **packet.locator.model_dump(mode="json", exclude_none=False),
            }
            for packet in packets
        ]
        visited_refs = sorted(
            {
                ":".join(
                    filter(
                        None,
                        (
                            location["document_id"],
                            f"page-{location['page_number']}"
                            if location["page_number"]
                            else "",
                            location["element_id"],
                            location["chunk_id"],
                            location["table_id"],
                            location["image_id"],
                        ),
                    )
                )
                for location in visited_locations
            }
        )
        unavailable_refs = [
            {
                "document_id": document_id,
                "source_version": scope.source_versions.get(document_id, ""),
                "reason": "no_scoped_evidence_returned",
            }
            for document_id in unavailable_documents
        ]
        if unavailable_documents:
            issues.append(
                VerificationIssue(
                    code="source_unavailable",
                    severity="error",
                    message="One or more requested documents produced no evidence.",
                    evidence_ids=[],
                )
            )
        missing_fields = [
            field
            for field in (
                "research_questions",
                "contributions",
                "methods",
                "datasets",
                "experiments",
                "limitations",
            )
            if not normalized[field]
        ]
        for field in missing_fields:
            issues.append(
                VerificationIssue(
                    code="unknown_field",
                    severity="warning",
                    message=f"No supported value was found for {field}.",
                    field=field,
                )
            )
        visual_evidence: list[dict[str, Any]] = []
        for packet in packets:
            if packet.locator.table_id or packet.locator.image_id:
                visual_evidence.append(
                    {
                        "evidence_id": packet.evidence_ref.evidence_id,
                        "document_id": packet.evidence_ref.source_id,
                        "locator": packet.locator.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "text": packet.text,
                        "visual_status": str(
                            packet.metadata.get("visual_status", "available")
                        ),
                        "unit": str(packet.metadata.get("unit", "")),
                        "footnote": str(packet.metadata.get("footnote", "")),
                    }
                )
            if (packet.locator.table_id or packet.locator.image_id) and str(
                packet.metadata.get("visual_status", "available")
            ) not in {"available", "described"}:
                issues.append(
                    VerificationIssue(
                        code="visual_content_unavailable",
                        severity="warning",
                        message="The visual locator is preserved but no verified visual interpretation is available.",
                        evidence_ids=[packet.evidence_ref.evidence_id],
                    )
                )

        coverage_attested_documents = {
            packet.evidence_ref.source_id
            for packet in packets
            if packet.metadata.get("document_coverage_complete") is True
        }
        coverage_complete = (
            bool(draft.get("coverage_complete"))
            and set(state["document_ids"]).issubset(coverage_attested_documents)
            and not unavailable_documents
        )
        if draft.get("coverage_complete") and not coverage_complete:
            issues.append(
                VerificationIssue(
                    code="coverage_not_attested",
                    severity="warning",
                    message=(
                        "The analysis provider claimed complete coverage without a "
                        "source-level coverage attestation."
                    ),
                    field="coverage",
                )
            )
        passed = coverage_complete and not missing_fields and not any(
            issue.severity == "error" for issue in issues
        )
        status = VerificationStatus.PASSED if passed else VerificationStatus.PARTIAL
        report = VerificationReport(
            status=status,
            checked_fields=fields,
            source_ids=visited_documents,
            citation_count=len(available_evidence),
            issues=issues,
        )
        content = {
            "reading_card": {
                field: normalized[field] if normalized[field] else ["unknown"]
                for field in fields
            },
            "field_evidence": field_evidence,
            "coverage": {
                "requested_document_ids": list(state["document_ids"]),
                "visited_refs": visited_refs,
                "unavailable_document_ids": unavailable_documents,
                "requested": requested_refs,
                "visited": visited_locations,
                "unavailable": unavailable_refs,
            },
            "visual_evidence": visual_evidence,
        }
        document_id = state["document_ids"][0] if state["document_ids"] else "unknown"
        artifact = DocumentAnalysisArtifact(
            artifact_id=_artifact_id(task, scope),
            producer_task_id=task.task_id,
            scope_ref=scope.scope_ref,
            document_id=document_id,
            document_version=scope.source_versions.get(document_id, ""),
            research_questions=normalized["research_questions"],
            contributions=normalized["contributions"],
            methods=normalized["methods"],
            datasets=normalized["datasets"],
            experiments=normalized["experiments"],
            limitations=normalized["limitations"],
            open_questions=normalized["open_questions"],
            content=content,
            claims=claims,
            evidence_refs=[packet.evidence_ref for packet in packets],
            source_coverage=SourceCoverage(
                complete=coverage_complete,
                covered_refs=visited_refs,
                missing_refs=[f"document:{item}" for item in unavailable_documents],
                notes=["Top-k evidence retrieval does not imply full-document coverage."]
                if not coverage_complete
                else [],
            ),
            verification_status=status,
            verification_report=report,
        )
        stored = self._artifacts.put(artifact)
        coverage = (
            len(visited_documents) / len(state["document_ids"])
            if state["document_ids"]
            else 0.0
        )
        result = TaskResult(
            task_id=task.task_id,
            attempt_id=f"{task.task_id}:1",
            status=TaskStatus.SUCCEEDED if passed else TaskStatus.PARTIAL,
            artifact_refs=[stored.ref()],
            evidence_refs=[packet.evidence_ref for packet in packets],
            coverage=coverage,
            unmet_requirements=[issue.field or issue.code for issue in issues],
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
        del dependency_results, memory_snapshot
        final = self._compiled.invoke({"task": task, "scope": scope})
        artifact = final["artifact"]
        return SpecialistExecution(
            result=final["result"],
            output=artifact.model_dump(mode="json"),
            direct_delivery=True,
        )


__all__ = [
    "DeterministicDocumentAnalysisProvider",
    "DocumentAnalysisProvider",
    "DocumentAnalystGraph",
    "DocumentAnalystState",
]
