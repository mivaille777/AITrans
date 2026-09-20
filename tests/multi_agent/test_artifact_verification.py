from __future__ import annotations

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.document_analyst_graph import DocumentAnalystGraph
from backend.models.agent_artifacts import ArtifactKind, EvidenceRef, VerificationStatus
from backend.models.agent_evidence import EvidencePacket, EvidenceSourceCategory
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec, TaskStatus


class OneEvidence:
    def retrieve_packets(self, **_kwargs):
        return (
            EvidencePacket(
                evidence_ref=EvidenceRef(
                    evidence_id="ev-1",
                    source_id="doc-a",
                    source_type="document_chunk",
                ),
                text="A supported source sentence.",
                source_category=EvidenceSourceCategory.DOCUMENT,
            ),
        )


class UnsupportedProvider:
    def analyze(self, **_kwargs):
        return {
            "research_questions": ["Invented unsupported question"],
            "contributions": [],
            "methods": [],
            "datasets": [],
            "experiments": [],
            "limitations": [],
            "open_questions": [],
            "field_evidence": {},
            "coverage_complete": True,
        }


def test_unsupported_fields_cannot_be_reported_as_completed_analysis() -> None:
    scope = ScopeContext.issue(scope_revision="verify", allowed_document_ids=["doc-a"])
    task = TaskSpec(
        task_id="document-verify",
        role=TaskRole.DOCUMENT,
        objective="Analyze",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope.scope_ref,
        allowed_tools=["search_knowledge_base"],
        target_source_ids=["doc-a"],
    )
    store = InMemoryArtifactStore()

    execution = DocumentAnalystGraph(
        evidence_service=OneEvidence(),
        artifact_store=store,
        provider=UnsupportedProvider(),
        max_retrieval_queries=1,
    ).execute(task=task, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.PARTIAL
    assert artifact.verification_status is VerificationStatus.PARTIAL
    assert any(
        issue.code == "unsupported_field" and issue.severity == "error"
        for issue in artifact.verification_report.issues
    )
    assert "analysis complete" not in str(execution.output).casefold()
