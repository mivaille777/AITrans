from __future__ import annotations

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.document_analyst_graph import DocumentAnalystGraph
from backend.models.agent_artifacts import ArtifactKind, EvidenceRef, VerificationStatus
from backend.models.agent_evidence import (
    EvidenceLocator,
    EvidencePacket,
    EvidenceSourceCategory,
)
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec, TaskStatus


def packet(
    evidence_id: str,
    text: str,
    *,
    page: int = 1,
    coverage_complete: bool = False,
) -> EvidencePacket:
    locator = EvidenceLocator(chunk_id=evidence_id, page_number=page)
    return EvidencePacket(
        evidence_ref=EvidenceRef(
            evidence_id=evidence_id,
            source_id="doc-a",
            source_type="document_chunk",
            source_version="v1",
            locator=locator.model_dump(mode="json", exclude_none=True),
        ),
        text=text,
        title="Paper A",
        source_category=EvidenceSourceCategory.DOCUMENT,
        relevance_score=0.9,
        locator=locator,
        metadata={"document_coverage_complete": coverage_complete},
    )


class Evidence:
    def __init__(self) -> None:
        self.calls = 0
        self.items = (
            packet(
                "ev-question",
                "The research question asks how to improve robust control.",
                coverage_complete=True,
            ),
            packet("ev-method", "The proposed method uses a Gaussian-process model."),
            packet("ev-data", "Experiments use the ControlBench dataset."),
            packet("ev-result", "Table 2 reports experiment accuracy of 91.2%.", page=7),
            packet("ev-limit", "A limitation is evaluation on one simulator."),
        )

    def retrieve_packets(self, *, query, scope, limit):
        del query, limit
        assert scope.allowed_document_ids == ["doc-a"]
        self.calls += 1
        return self.items


def task() -> TaskSpec:
    return TaskSpec(
        task_id="document-1",
        role=TaskRole.DOCUMENT,
        objective="Analyze paper A",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref="scope-placeholder",
        allowed_tools=["search_knowledge_base"],
        target_source_ids=["doc-a"],
    )


def test_document_analyst_builds_source_bound_reading_card_with_bounded_queries() -> None:
    scope = ScopeContext.issue(
        scope_revision="doc-a-v1",
        allowed_document_ids=["doc-a"],
        source_versions={"doc-a": "v1"},
    )
    spec = task().model_copy(update={"scope_ref": scope.scope_ref})
    evidence = Evidence()
    store = InMemoryArtifactStore()
    analyst = DocumentAnalystGraph(evidence_service=evidence, artifact_store=store)

    execution = analyst.execute(
        task=spec,
        scope=scope,
        dependency_results={},
        memory_snapshot={},
    )
    artifact = store.get(
        execution.result.artifact_refs[0].artifact_id,
        execution.result.artifact_refs[0].version,
    )

    assert evidence.calls == 3
    assert execution.direct_delivery is True
    assert execution.result.status is TaskStatus.PARTIAL
    assert artifact is not None
    assert artifact.document_id == "doc-a"
    assert artifact.methods == ["The proposed method uses a Gaussian-process model."]
    assert artifact.datasets == ["Experiments use the ControlBench dataset."]
    assert artifact.experiments == ["Table 2 reports experiment accuracy of 91.2%."]
    assert artifact.verification_status is VerificationStatus.PARTIAL
    assert artifact.source_coverage.complete is False
    assert all(claim.evidence_ids for claim in artifact.claims)
    assert "page-7" in " ".join(artifact.source_coverage.covered_refs)


class CompleteProvider:
    def analyze(self, *, objective, document_ids, evidence):
        del objective, document_ids
        evidence_id = evidence[0].evidence_ref.evidence_id
        return {
            "research_questions": ["Question"],
            "contributions": ["Contribution"],
            "methods": ["Method"],
            "datasets": ["Dataset"],
            "experiments": ["Experiment"],
            "limitations": ["Limitation"],
            "open_questions": ["Open question"],
            "field_evidence": {
                field: [evidence_id]
                for field in (
                    "research_questions",
                    "contributions",
                    "methods",
                    "datasets",
                    "experiments",
                    "limitations",
                    "open_questions",
                )
            },
            "coverage_complete": True,
        }


def test_document_analyst_can_pass_only_with_complete_supported_fields() -> None:
    scope = ScopeContext.issue(scope_revision="complete", allowed_document_ids=["doc-a"])
    spec = task().model_copy(update={"scope_ref": scope.scope_ref})
    store = InMemoryArtifactStore()
    analyst = DocumentAnalystGraph(
        evidence_service=Evidence(),
        artifact_store=store,
        provider=CompleteProvider(),
        max_retrieval_queries=1,
    )

    execution = analyst.execute(task=spec, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.SUCCEEDED
    assert execution.direct_delivery is True
    assert artifact.verification_status is VerificationStatus.PASSED
    assert artifact.source_coverage.complete is True


class EvidenceWithoutCoverageAttestation(Evidence):
    def retrieve_packets(self, *, query, scope, limit):
        return tuple(
            item.model_copy(update={"metadata": {}})
            for item in super().retrieve_packets(
                query=query,
                scope=scope,
                limit=limit,
            )
        )


def test_provider_cannot_turn_partial_retrieval_into_full_document_coverage() -> None:
    scope = ScopeContext.issue(
        scope_revision="unattested",
        allowed_document_ids=["doc-a"],
    )
    spec = task().model_copy(update={"scope_ref": scope.scope_ref})
    store = InMemoryArtifactStore()

    execution = DocumentAnalystGraph(
        evidence_service=EvidenceWithoutCoverageAttestation(),
        artifact_store=store,
        provider=CompleteProvider(),
        max_retrieval_queries=1,
    ).execute(task=spec, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.PARTIAL
    assert artifact.source_coverage.complete is False
    assert "coverage_not_attested" in {
        issue.code for issue in artifact.verification_report.issues
    }
