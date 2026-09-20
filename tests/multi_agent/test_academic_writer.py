from __future__ import annotations

from typing import ClassVar

from app.ai.gateway import LLMGateway
from app.ai.models import AITextAction
from app.ai.output_guard import validate_model_output
from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.academic_writer_graph import AcademicWriterGraph
from backend.models.agent_artifacts import (
    ArtifactKind,
    ClaimRecord,
    DocumentAnalysisArtifact,
    EvidenceRef,
    ManuscriptSectionArtifact,
    OutlineArtifact,
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


def document(scope_ref: str) -> DocumentAnalysisArtifact:
    return DocumentAnalysisArtifact(
        artifact_id="document-writing-a",
        producer_task_id="document-1",
        scope_ref=scope_ref,
        document_id="paper-a",
        contributions=["The paper introduces bounded adaptive control."],
        methods=["The method uses a two-stage estimator."],
        limitations=["Evaluation covers one benchmark."],
        content={
            "source_metadata": {
                "paper-a": {
                    "title": "Bounded Adaptive Control",
                    "authors": ["A. Researcher"],
                    "year": "2025",
                }
            }
        },
        claims=[
            ClaimRecord(
                claim_id="claim-a",
                statement="The method uses a two-stage estimator.",
                evidence_ids=["ev-a"],
            )
        ],
        evidence_refs=[
            EvidenceRef(
                evidence_id="ev-a",
                source_id="paper-a",
                source_type="document_chunk",
            )
        ],
        source_coverage=SourceCoverage(complete=True, covered_refs=["paper-a"]),
        verification_status=VerificationStatus.PASSED,
    )


def task(scope_ref: str, kind: ArtifactKind, objective: str) -> TaskSpec:
    return TaskSpec(
        task_id="writer-1",
        role=TaskRole.WRITER,
        objective=objective,
        depends_on=["document-1"],
        required=True,
        expected_output_kind=kind,
        scope_ref=scope_ref,
        allowed_tools=["polish_selection"],
    )


def dependencies(artifact: DocumentAnalysisArtifact) -> dict[str, TaskResult]:
    return {
        "document-1": TaskResult(
            task_id="document-1",
            attempt_id="document-1:1",
            status=TaskStatus.SUCCEEDED,
            artifact_refs=[artifact.ref()],
        )
    }


def test_academic_writer_builds_evidence_mapped_section_without_fake_metadata() -> None:
    scope = ScopeContext.issue(
        scope_revision="writer",
        workspace_id="workspace-a",
        allowed_document_ids=["paper-a"],
    )
    store = InMemoryArtifactStore()
    source = store.put(document(scope.scope_ref))

    execution = AcademicWriterGraph(artifact_store=store).execute(
        task=task(scope.scope_ref, ArtifactKind.MANUSCRIPT_SECTION, "Draft discussion"),
        scope=scope,
        dependency_results=dependencies(source),
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert isinstance(artifact, ManuscriptSectionArtifact)
    assert execution.direct_delivery is True
    assert execution.result.status is TaskStatus.SUCCEEDED
    assert artifact.content["draft_only"] is True
    assert artifact.content["applied"] is False
    assert artifact.paragraph_ids
    assert all(artifact.claim_source_map[item] for item in artifact.paragraph_ids)
    assert all(claim.evidence_ids for claim in artifact.claims)
    assert artifact.references[0].title == "Bounded Adaptive Control"
    assert artifact.references[0].authors == ["A. Researcher"]
    assert artifact.references[0].year == "2025"
    assert artifact.references[0].doi == ""
    assert artifact.references[0].missing_fields == ["doi"]


def test_writer_generates_typed_outline_when_plan_requests_outline() -> None:
    scope = ScopeContext.issue(
        scope_revision="outline",
        workspace_id="workspace-a",
        allowed_document_ids=["paper-a"],
    )
    store = InMemoryArtifactStore()
    source = store.put(document(scope.scope_ref))

    execution = AcademicWriterGraph(artifact_store=store).execute(
        task=task(scope.scope_ref, ArtifactKind.OUTLINE, "Create a paper outline"),
        scope=scope,
        dependency_results=dependencies(source),
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert isinstance(artifact, OutlineArtifact)
    assert execution.result.status is TaskStatus.SUCCEEDED
    assert [item.section_id for item in artifact.sections] == [
        "introduction",
        "related-work",
        "methods",
        "results",
        "discussion",
    ]


def test_experiment_section_requires_user_supplied_results() -> None:
    scope = ScopeContext.issue(
        scope_revision="experiment",
        workspace_id="workspace-a",
        allowed_document_ids=["paper-a"],
    )
    store = InMemoryArtifactStore()
    source = store.put(document(scope.scope_ref))
    writer = AcademicWriterGraph(artifact_store=store)
    spec = task(scope.scope_ref, ArtifactKind.MANUSCRIPT_SECTION, "Draft experiment results")

    missing = writer.execute(
        task=spec,
        scope=scope,
        dependency_results=dependencies(source),
        memory_snapshot={},
    )
    missing_artifact = store.get(missing.result.artifact_refs[0].artifact_id, 1)

    assert missing.result.status is TaskStatus.PARTIAL
    assert "[Missing user-supplied experiment results]" in missing_artifact.markdown
    assert "user_supplied_experiment_results" in missing_artifact.missing_inputs

    complete_scope = ScopeContext.issue(
        scope_revision="experiment-complete",
        workspace_id="workspace-a",
        allowed_document_ids=["paper-a"],
    )
    complete_store = InMemoryArtifactStore()
    complete_source = complete_store.put(document(complete_scope.scope_ref))
    complete = AcademicWriterGraph(artifact_store=complete_store).execute(
        task=task(
            complete_scope.scope_ref,
            ArtifactKind.MANUSCRIPT_SECTION,
            "Draft experiment results",
        ),
        scope=complete_scope,
        dependency_results=dependencies(complete_source),
        memory_snapshot={
            "user_supplied": [
                {
                    "evidence_id": "user-result-1",
                    "source_id": "experiment-1",
                    "text": "Our controller achieved an IAE of 12.4.",
                }
            ]
        },
    )
    complete_artifact = complete_store.get(complete.result.artifact_refs[0].artifact_id, 1)

    assert complete.result.status is TaskStatus.SUCCEEDED
    assert complete_artifact.claims[0].category == "user_supplied"
    assert complete_artifact.claims[0].evidence_ids == ["user-result-1"]


class Settings:
    user_data: ClassVar[dict[str, dict[str, str]]] = {
        "ai": {"provider": "deepseek", "model": "deepseek-v4-pro"}
    }

    def get(self, section: str, key: str, default: str):
        assert section == "ai"
        return self.user_data["ai"].get(key, default)


def test_academic_writer_gateway_route_is_lazy_and_uses_existing_provider_allowlist() -> None:
    gateway = LLMGateway(settings_factory=Settings)

    route = gateway.route("academic_writer")
    service = gateway.create_text_service("academic_writer")

    assert route.provider == "deepseek"
    assert route.model == "deepseek-v4-pro"
    assert service.route.role == "academic_writer"
    assert service._service is None


def test_language_transform_guard_preserves_numbers_units_and_citations() -> None:
    source = "Accuracy was 91.2% with latency 24 ms [1]."

    valid = validate_model_output(
        "\u51c6\u786e\u7387\u4e3a 91.2%\uff0c\u5ef6\u8fdf\u4e3a 24 ms [1]\u3002",
        source_text=source,
        action=AITextAction.TRANSLATE,
    )
    missing_citation = validate_model_output(
        "\u51c6\u786e\u7387\u4e3a 91.2%\uff0c\u5ef6\u8fdf\u4e3a 24 ms\u3002",
        source_text=source,
        action=AITextAction.TRANSLATE,
    )

    assert valid.valid is True
    assert missing_citation.valid is False
    assert missing_citation.reason == "citation_mapping_changed"
