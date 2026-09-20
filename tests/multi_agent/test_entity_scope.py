from backend.agent_core.orchestration.artifact_store import InMemoryArtifactStore
from backend.agent_graph.knowledge_curator_graph import KnowledgeCuratorGraph
from backend.knowledge.domain import KnowledgeItemType
from backend.models.agent_artifacts import ArtifactKind
from backend.models.agent_tasks import TaskRole, TaskSpec
from tests.multi_agent._curator_support import curator_stack


def test_same_name_entity_outside_workspace_is_not_an_auto_merge_candidate(tmp_path):
    _, knowledge, _, _, _, _, scope = curator_stack(tmp_path)
    outside = knowledge.create_item(item_type=KnowledgeItemType.CONCEPT, title="Shared Name", metadata={"workspace_id": "workspace-b"})

    class Provider:
        def curate(self, **_):
            return {"items": [{"draft_id": "a", "item_type": "concept", "title": "Shared Name", "source_ids": ["paper-a"]}]}

    store = InMemoryArtifactStore()
    graph = KnowledgeCuratorGraph(artifact_store=store, knowledge_workspace=knowledge, provider=Provider())
    task = TaskSpec(task_id="curator-1", role=TaskRole.CURATOR, objective="curate", required=True, expected_output_kind=ArtifactKind.KNOWLEDGE_DRAFT, scope_ref=scope.scope_ref)
    execution = graph.execute(task=task, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)
    assert artifact.items[0].duplicate_candidate_ids == []
    assert outside.item_id not in artifact.items[0].duplicate_candidate_ids


def test_scoped_same_name_candidate_is_suggested_but_not_merged(tmp_path):
    _, knowledge, _, _, _, _, scope = curator_stack(tmp_path)
    existing = knowledge.create_item(item_type=KnowledgeItemType.CONCEPT, title="Shared Name", metadata={"workspace_id": scope.workspace_id})
    scope = scope.model_copy(update={"allowed_item_ids": [existing.item_id]})

    class Provider:
        def curate(self, **_):
            return {"items": [{"draft_id": "a", "item_type": "concept", "title": "Shared Name", "source_ids": ["paper-a"]}]}

    store = InMemoryArtifactStore()
    graph = KnowledgeCuratorGraph(artifact_store=store, knowledge_workspace=knowledge, provider=Provider())
    task = TaskSpec(task_id="curator-1", role=TaskRole.CURATOR, objective="curate", required=True, expected_output_kind=ArtifactKind.KNOWLEDGE_DRAFT, scope_ref=scope.scope_ref)
    execution = graph.execute(task=task, scope=scope, dependency_results={}, memory_snapshot={})
    artifact = store.get(execution.result.artifact_refs[0].artifact_id, 1)
    assert artifact.items[0].duplicate_candidate_ids == [existing.item_id]
    assert len(knowledge.list_items()) == 1
