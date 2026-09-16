from __future__ import annotations

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.document_analyst_graph import DocumentAnalystGraph
from backend.models.agent_artifacts import ArtifactKind, EvidenceRef
from backend.models.agent_evidence import (
    EvidenceLocator,
    EvidencePacket,
    EvidenceSourceCategory,
)
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec, TaskStatus


class PartialDocumentEvidence:
    def retrieve_packets(self, *, query, scope, limit):
        del query, limit
        assert scope.allowed_document_ids == ["doc-a", "doc-b"]
        locator = EvidenceLocator(
            chunk_id="abstract-1",
            page_number=1,
            section_path=["abstract"],
        )
        return (
            EvidencePacket(
                evidence_ref=EvidenceRef(
                    evidence_id="abstract-1",
                    source_id="doc-a",
                    source_type="document_chunk",
                    source_version="v1",
                    locator=locator.model_dump(mode="json", exclude_none=True),
                ),
                text="Only the abstract is available; the research objective is robust control.",
                source_category=EvidenceSourceCategory.DOCUMENT,
                locator=locator,
            ),
        )


def test_partial_document_coverage_records_requested_visited_and_unavailable() -> None:
    scope = ScopeContext.issue(
        scope_revision="partial-coverage",
        allowed_document_ids=["doc-a", "doc-b"],
        source_versions={"doc-a": "v1", "doc-b": "v2"},
    )
    task = TaskSpec(
        task_id="document-partial",
        role=TaskRole.DOCUMENT,
        objective="Analyze the full papers",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope.scope_ref,
        allowed_tools=["search_knowledge_base"],
        target_source_ids=["doc-a", "doc-b"],
    )
    store = InMemoryArtifactStore()

    execution = DocumentAnalystGraph(
        evidence_service=PartialDocumentEvidence(),
        artifact_store=store,
        max_retrieval_queries=1,
    ).execute(task=task, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)
    coverage = artifact.content["coverage"]

    assert execution.result.status is TaskStatus.PARTIAL
    assert [item["document_id"] for item in coverage["requested"]] == [
        "doc-a",
        "doc-b",
    ]
    assert coverage["visited"][0]["section_path"] == ["abstract"]
    assert coverage["visited"][0]["page_number"] == 1
    assert coverage["unavailable"] == [
        {
            "document_id": "doc-b",
            "source_version": "v2",
            "reason": "no_scoped_evidence_returned",
        }
    ]
    assert artifact.source_coverage.complete is False
    assert "Top-k evidence retrieval does not imply full-document coverage." in (
        artifact.source_coverage.notes
    )
    assert artifact.experiments == []
