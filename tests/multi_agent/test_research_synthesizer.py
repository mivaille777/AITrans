from __future__ import annotations

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.research_synthesizer_graph import ResearchSynthesizerGraph
from backend.models.agent_artifacts import (
    ArtifactKind,
    ClaimRecord,
    DocumentAnalysisArtifact,
    EvidenceRef,
    SourceCoverage,
    VerificationStatus,
)
from backend.models.agent_tasks import (
    ScopeContext,
    TaskResult,
    TaskRole,
    TaskSpec,
    TaskStatus,
)


def document(
    document_id: str,
    dataset: str,
    accuracy: str,
    task_id: str,
    *,
    coverage_complete: bool = True,
):
    evidence_id = f"ev-{document_id}"
    return DocumentAnalysisArtifact(
        artifact_id=f"artifact-{document_id}",
        producer_task_id=task_id,
        scope_ref="scope",
        document_id=document_id,
        methods=["Transformer"],
        datasets=[dataset],
        experiments=[accuracy],
        limitations=[f"Limit of {document_id}"],
        content={
            "field_evidence": {
                "methods": [evidence_id],
                "datasets": [evidence_id],
                "experiments": [evidence_id],
                "limitations": [evidence_id],
            }
        },
        claims=[ClaimRecord(claim_id=f"claim-{document_id}", statement=accuracy, evidence_ids=[evidence_id])],
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                source_id=document_id,
                source_type="document_chunk",
            )
        ],
        source_coverage=SourceCoverage(
            complete=coverage_complete,
            covered_refs=[document_id],
        ),
        verification_status=(
            VerificationStatus.PASSED
            if coverage_complete
            else VerificationStatus.PARTIAL
        ),
    )


def research_task(scope_ref: str, objective: str = "Compare papers") -> TaskSpec:
    return TaskSpec(
        task_id="research-1",
        role=TaskRole.RESEARCH,
        objective=objective,
        depends_on=["document-1", "document-2"],
        required=True,
        expected_output_kind=ArtifactKind.COMPARISON,
        scope_ref=scope_ref,
        allowed_tools=["analyze_cross_document_research"],
    )


def test_research_synthesizer_compares_conditions_without_extra_retrieval() -> None:
    scope = ScopeContext.issue(
        scope_revision="compare",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()
    first = store.put(document("doc-a", "Dataset-A", "Accuracy 91.2%", "document-1"))
    second = store.put(document("doc-b", "Dataset-B", "Accuracy 94.0%", "document-2"))
    dependencies = {
        "document-1": TaskResult(
            task_id="document-1",
            attempt_id="a1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[first.ref()],
        ),
        "document-2": TaskResult(
            task_id="document-2",
            attempt_id="a2",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[second.ref()],
        ),
    }

    execution = ResearchSynthesizerGraph(artifact_store=store).execute(
        task=research_task(scope.scope_ref),
        scope=scope,
        dependency_results=dependencies,
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.SUCCEEDED
    assert execution.direct_delivery is True
    assert artifact.verification_status is VerificationStatus.PASSED
    experiment_cells = [cell for cell in artifact.cells if cell.dimension == "experiments"]
    assert [cell.value for cell in experiment_cells] == ["Accuracy 91.2%", "Accuracy 94.0%"]
    assert [cell.conditions for cell in experiment_cells] == ["Dataset-A", "Dataset-B"]
    assert any("differ in datasets" in item for item in artifact.conflicts)
    assert len(artifact.lineage) == 2


class Review:
    def __init__(self, accepted_count: int) -> None:
        self.accepted_count = accepted_count

    def snapshot(self, **_kwargs):
        return type("Snapshot", (), {"accepted_count": self.accepted_count})()


def test_formal_literature_synthesis_requires_stage20_accepted_evidence() -> None:
    scope = ScopeContext.issue(
        scope_revision="review",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()
    first = store.put(document("doc-a", "A", "91%", "document-1"))
    second = store.put(document("doc-b", "B", "92%", "document-2"))
    dependencies = {
        "document-1": TaskResult(task_id="document-1", attempt_id="a1", status=TaskStatus.SUCCEEDED, artifact_refs=[first.ref()]),
        "document-2": TaskResult(task_id="document-2", attempt_id="a2", status=TaskStatus.SUCCEEDED, artifact_refs=[second.ref()]),
    }

    blocked = ResearchSynthesizerGraph(
        artifact_store=store,
        evidence_review_service=Review(0),
    ).execute(
        task=research_task(scope.scope_ref, "Draft a Related Work literature review"),
        scope=scope,
        dependency_results=dependencies,
        memory_snapshot={},
    )

    assert blocked.result.status is TaskStatus.PARTIAL
    assert "review_gate_not_satisfied" in blocked.result.unmet_requirements


def test_authorized_memory_hypothesis_is_marked_and_never_becomes_document_fact() -> None:
    scope = ScopeContext.issue(
        scope_revision="memory-context",
        workspace_id="workspace-a",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()
    first = store.put(document("doc-a", "A", "91%", "document-1"))
    second = store.put(document("doc-b", "B", "92%", "document-2"))
    dependencies = {
        "document-1": TaskResult(
            task_id="document-1",
            attempt_id="a1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[first.ref()],
        ),
        "document-2": TaskResult(
            task_id="document-2",
            attempt_id="a2",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[second.ref()],
        ),
    }

    execution = ResearchSynthesizerGraph(artifact_store=store).execute(
        task=research_task(scope.scope_ref),
        scope=scope,
        dependency_results=dependencies,
        memory_snapshot={
            "snapshot_id": "memory-7",
            "hypotheses": [
                {
                    "id": "hypothesis-1",
                    "kind": "hypothesis",
                    "text": "A shared benchmark may explain the apparent gap.",
                    "authorized": True,
                },
                {
                    "id": "private-1",
                    "kind": "hypothesis",
                    "text": "This item is outside the authorized snapshot.",
                    "authorized": False,
                },
            ],
        },
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.SUCCEEDED
    assert artifact.content["memory_snapshot_ref"] == "memory-7"
    assert artifact.content["memory_context_ids"] == ["hypothesis-1"]
    assert [item.status for item in artifact.research_hypotheses] == ["hypothesis"]
    assert artifact.research_hypotheses[0].basis_ids == ["hypothesis-1"]
    assert all("shared benchmark" not in cell.value for cell in artifact.cells)


def test_partial_document_input_cannot_be_reported_as_complete_comparison() -> None:
    scope = ScopeContext.issue(
        scope_revision="partial-input",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()
    first = store.put(document("doc-a", "A", "91%", "document-1"))
    second = store.put(
        document(
            "doc-b",
            "B",
            "92%",
            "document-2",
            coverage_complete=False,
        )
    )
    dependencies = {
        "document-1": TaskResult(
            task_id="document-1",
            attempt_id="a1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[first.ref()],
        ),
        "document-2": TaskResult(
            task_id="document-2",
            attempt_id="a2",
            status=TaskStatus.PARTIAL,
            artifact_refs=[second.ref()],
        ),
    }

    execution = ResearchSynthesizerGraph(artifact_store=store).execute(
        task=research_task(scope.scope_ref),
        scope=scope,
        dependency_results=dependencies,
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.PARTIAL
    assert artifact.verification_status is VerificationStatus.PARTIAL
    assert "partial_input_coverage" in execution.result.warnings


def test_research_synthesizer_rejects_artifact_reference_hash_mismatch() -> None:
    scope = ScopeContext.issue(
        scope_revision="hash-mismatch",
        allowed_document_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()
    first = store.put(document("doc-a", "A", "91%", "document-1"))
    second = store.put(document("doc-b", "B", "92%", "document-2"))
    forged_ref = first.ref().model_copy(update={"content_hash": "0" * 64})
    dependencies = {
        "document-1": TaskResult(
            task_id="document-1",
            attempt_id="a1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[forged_ref],
        ),
        "document-2": TaskResult(
            task_id="document-2",
            attempt_id="a2",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[second.ref()],
        ),
    }

    execution = ResearchSynthesizerGraph(artifact_store=store).execute(
        task=research_task(scope.scope_ref),
        scope=scope,
        dependency_results=dependencies,
        memory_snapshot={},
    )

    assert execution.result.status is TaskStatus.PARTIAL
    assert "input_artifact_hash_mismatch" in execution.result.unmet_requirements
