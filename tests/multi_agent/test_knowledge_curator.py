from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.knowledge_curator_graph import KnowledgeCuratorGraph
from backend.knowledge.repository import SqliteKnowledgeRepository
from backend.knowledge.service import KnowledgeWorkspaceService
from backend.models.agent_artifacts import ArtifactKind, KnowledgeDraftArtifact
from backend.models.agent_tasks import TaskResult, TaskRole, TaskSpec, TaskStatus
from tests.multi_agent._curator_support import curator_stack, source_artifact


def test_curator_builds_typed_reviewable_drafts_without_writing_business_stores(tmp_path):
    _, _, _, _, _, _, scope = curator_stack(tmp_path)
    artifacts = InMemoryArtifactStore()
    source = artifacts.put(source_artifact(scope))
    knowledge = KnowledgeWorkspaceService(SqliteKnowledgeRepository(tmp_path / "graph.sqlite3"))
    task = TaskSpec(
        task_id="curator-1",
        role=TaskRole.CURATOR,
        objective="整理为研究笔记和知识卡",
        depends_on=["document-1"],
        required=True,
        expected_output_kind=ArtifactKind.KNOWLEDGE_DRAFT,
        scope_ref=scope.scope_ref,
    )
    execution = KnowledgeCuratorGraph(
        artifact_store=artifacts,
        knowledge_workspace=knowledge,
    ).execute(
        task=task,
        scope=scope,
        dependency_results={
            "document-1": TaskResult(
                task_id="document-1",
                attempt_id="document-1:1",
                status=TaskStatus.SUCCEEDED,
                artifact_refs=[source.ref()],
            )
        },
        memory_snapshot={},
    )
    artifact = artifacts.get(execution.result.artifact_refs[0].artifact_id, 1)

    assert isinstance(artifact, KnowledgeDraftArtifact)
    assert execution.result.status is TaskStatus.SUCCEEDED
    assert artifact.notes[0].source_quote
    assert artifact.notes[0].user_note == ""
    assert artifact.items[0].item_type == "concept"
    assert artifact.items[0].subtype == "method"
    assert artifact.content["approval_required"] is True
    assert knowledge.list_items() == []


def test_curator_rejects_unscoped_relation_endpoint(tmp_path):
    _, knowledge, _, _, _, _, scope = curator_stack(tmp_path)

    class Provider:
        def curate(self, **_):
            return {
                "items": [{"draft_id": "inside", "item_type": "insight", "title": "Inside"}],
                "relation_proposals": [{"proposal_id": "bad", "source_draft_or_item_id": "inside", "target_draft_or_item_id": "outside", "relation_type": "related_to"}],
            }

    graph = KnowledgeCuratorGraph(artifact_store=InMemoryArtifactStore(), knowledge_workspace=knowledge, provider=Provider())
    task = TaskSpec(task_id="curator-1", role=TaskRole.CURATOR, objective="curate", required=True, expected_output_kind=ArtifactKind.KNOWLEDGE_DRAFT, scope_ref=scope.scope_ref)
    result = graph.execute(task=task, scope=scope, dependency_results={}, memory_snapshot={})
    assert result.result.status is TaskStatus.PARTIAL
    assert "invalid_relation_endpoint" in result.result.unmet_requirements
