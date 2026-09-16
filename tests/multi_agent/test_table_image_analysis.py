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


class VisualEvidence:
    def __init__(self, *, status: str) -> None:
        self.status = status

    def retrieve_packets(self, *, query, scope, limit):
        del query, limit
        locator = EvidenceLocator(
            chunk_id="table-text-1",
            page_number=4,
            element_id="table-a-1",
            table_id="table-a-1",
            image_id="figure-a-1",
        )
        return (
            EvidencePacket(
                evidence_ref=EvidenceRef(
                    evidence_id="visual-1",
                    source_id="doc-a",
                    source_type="document_visual",
                    locator=locator.model_dump(mode="json", exclude_none=True),
                ),
                text="Table 1 reports experiment accuracy of 91.0% and latency of 24 ms.",
                source_category=EvidenceSourceCategory.DOCUMENT,
                locator=locator,
                metadata={
                    "visual_status": self.status,
                    "unit": "% and ms",
                    "footnote": "Accuracy uses split A1.",
                },
            ),
        )


def _task(scope_ref: str) -> TaskSpec:
    return TaskSpec(
        task_id="document-visual",
        role=TaskRole.DOCUMENT,
        objective="Explain table 1 and figure 1",
        required=True,
        expected_output_kind=ArtifactKind.DOCUMENT_ANALYSIS,
        scope_ref=scope_ref,
        allowed_tools=["search_knowledge_base"],
        target_source_ids=["doc-a"],
    )


def test_table_values_units_footnote_and_locator_remain_source_bound() -> None:
    scope = ScopeContext.issue(scope_revision="visual", allowed_document_ids=["doc-a"])
    store = InMemoryArtifactStore()

    execution = DocumentAnalystGraph(
        evidence_service=VisualEvidence(status="described"),
        artifact_store=store,
        max_retrieval_queries=1,
    ).execute(
        task=_task(scope.scope_ref),
        scope=scope,
        dependency_results={},
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)
    visual = artifact.content["visual_evidence"][0]

    assert visual["locator"]["page_number"] == 4
    assert visual["locator"]["table_id"] == "table-a-1"
    assert visual["locator"]["image_id"] == "figure-a-1"
    assert visual["unit"] == "% and ms"
    assert visual["footnote"] == "Accuracy uses split A1."
    assert artifact.experiments == [
        "Table 1 reports experiment accuracy of 91.0% and latency of 24 ms."
    ]


def test_missing_visual_capability_is_an_explicit_partial_result() -> None:
    scope = ScopeContext.issue(
        scope_revision="visual-degraded",
        allowed_document_ids=["doc-a"],
    )
    store = InMemoryArtifactStore()

    execution = DocumentAnalystGraph(
        evidence_service=VisualEvidence(status="unavailable"),
        artifact_store=store,
        max_retrieval_queries=1,
    ).execute(
        task=_task(scope.scope_ref),
        scope=scope,
        dependency_results={},
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)
    issue_codes = {issue.code for issue in artifact.verification_report.issues}

    assert execution.result.status is TaskStatus.PARTIAL
    assert "visual_content_unavailable" in issue_codes
    assert artifact.content["visual_evidence"][0]["visual_status"] == "unavailable"
    assert artifact.evidence_refs[0].locator["page_number"] == 4
