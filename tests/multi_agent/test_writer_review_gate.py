from __future__ import annotations

from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.academic_writer_graph import AcademicWriterGraph
from backend.models.agent_artifacts import (
    ArtifactKind,
    ManuscriptSectionArtifact,
    VerificationStatus,
)
from backend.models.agent_tasks import ScopeContext, TaskRole, TaskSpec, TaskStatus
from backend.models.evidence_review import (
    AgentLiteratureSynthesisResponse,
    LiteratureSynthesisItem,
    LiteratureSynthesisPlan,
)


class Literature:
    def __init__(self, *, accepted: bool) -> None:
        self.accepted = accepted
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(dict(kwargs))
        accepted_item = LiteratureSynthesisItem(
            entry_id="entry-a",
            statement="Reviewed evidence supports bounded adaptation.",
            machine_status="supported",
            review_status="accepted",
            bucket="consensus",
            document_ids=["paper-a"],
            evidence_ids=["review-ev-a"],
        )
        plan = LiteratureSynthesisPlan(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            included_count=1 if self.accepted else 0,
            excluded_count=2,
            consensus=[accepted_item] if self.accepted else [],
            draft_markdown=(
                "Reviewed evidence supports bounded adaptation [1]."
                if self.accepted
                else ""
            ),
        )
        return AgentLiteratureSynthesisResponse(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            status="completed" if self.accepted else "no_evidence",
            output_text=plan.draft_markdown,
            provider="policy",
            model="stage20",
            prompt_id="research.literature_synthesis@test",
            included_count=plan.included_count,
            excluded_count=plan.excluded_count,
            evidence_count=plan.included_count,
            citation_count=plan.included_count,
            plan=plan,
        )


def writer_task(scope_ref: str) -> TaskSpec:
    return TaskSpec(
        task_id="writer-related-work",
        role=TaskRole.WRITER,
        objective="Draft a Related Work literature review",
        required=True,
        expected_output_kind=ArtifactKind.MANUSCRIPT_SECTION,
        scope_ref=scope_ref,
        allowed_tools=["polish_selection"],
    )


def test_related_work_uses_only_stage20_reviewed_synthesis() -> None:
    scope = ScopeContext.issue(
        scope_revision="related-work",
        workspace_id="workspace-a",
    )
    store = InMemoryArtifactStore()
    literature = Literature(accepted=True)

    execution = AcademicWriterGraph(
        artifact_store=store,
        literature_synthesis_service=literature,
    ).execute(
        task=writer_task(scope.scope_ref),
        scope=scope,
        dependency_results={},
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.SUCCEEDED
    assert isinstance(artifact, ManuscriptSectionArtifact)
    assert artifact.verification_status is VerificationStatus.PASSED
    assert artifact.claims[0].evidence_ids == ["review-ev-a"]
    assert artifact.evidence_refs[0].source_type == "review_ledger"
    assert artifact.content["review_prompt_id"] == "research.literature_synthesis@test"
    assert literature.calls[0]["workspace_id"] == "workspace-a"


def test_related_work_without_accepted_evidence_stays_partial_placeholder() -> None:
    scope = ScopeContext.issue(
        scope_revision="related-work-empty",
        workspace_id="workspace-a",
    )
    store = InMemoryArtifactStore()

    execution = AcademicWriterGraph(
        artifact_store=store,
        literature_synthesis_service=Literature(accepted=False),
    ).execute(
        task=writer_task(scope.scope_ref),
        scope=scope,
        dependency_results={},
        memory_snapshot={},
    )
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert execution.result.status is TaskStatus.PARTIAL
    assert artifact.markdown == "[Missing verified research material]"
    assert "accepted_stage20_evidence" in artifact.missing_inputs
    assert artifact.claims[0].category == "suggestion"
    assert artifact.claims[0].evidence_ids == []
