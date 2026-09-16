import pytest

from backend.models.agent_artifacts import KnowledgeItemDraft
from backend.services.curator_commit_service import CuratorCommitConflictError
from tests.multi_agent._curator_support import curator_stack, draft_artifact


def test_repeated_commit_replays_one_canonical_item(tmp_path):
    artifacts, knowledge, _, _, _, service, scope = curator_stack(tmp_path)
    artifact = artifacts.put(draft_artifact(scope, items=[KnowledgeItemDraft(draft_id="i1", item_type="insight", title="One", summary="Supported", source_ids=["paper-a"])]))
    first = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="same-op", scope=scope)
    second = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="same-op", scope=scope)
    assert first.status == "completed"
    assert second.replayed is True
    assert first.results[0].object_id == second.results[0].object_id
    assert len(knowledge.list_items()) == 1


def test_operation_id_is_bound_to_payload_scope_and_targets(tmp_path):
    artifacts, _, _, _, _, service, scope = curator_stack(tmp_path)
    one = artifacts.put(draft_artifact(scope, artifact_id="draft-one", items=[KnowledgeItemDraft(draft_id="i1", item_type="insight", title="One", source_ids=["paper-a"])]))
    two = artifacts.put(draft_artifact(scope, artifact_id="draft-two", items=[KnowledgeItemDraft(draft_id="i2", item_type="insight", title="Two", source_ids=["paper-a"])]))
    service.apply(artifact_id=one.artifact_id, artifact_version=1, operation_id="bound-op", scope=scope)
    with pytest.raises(CuratorCommitConflictError):
        service.apply(artifact_id=two.artifact_id, artifact_version=1, operation_id="bound-op", scope=scope)
