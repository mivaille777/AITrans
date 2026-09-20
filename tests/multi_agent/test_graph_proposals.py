from backend.knowledge.domain import (
    KnowledgeItemType,
    KnowledgeRelationSuggestionStatus,
)
from backend.models.agent_artifacts import RelationProposal
from backend.services.knowledge_relation_suggestion_service import (
    KnowledgeRelationSuggestionService,
)
from tests.multi_agent._curator_support import curator_stack, draft_artifact


def test_relation_proposal_stays_pending_until_idempotent_accept(tmp_path):
    artifacts, knowledge, suggestions, _, _, commit, scope = curator_stack(tmp_path)
    left = knowledge.create_item(item_type=KnowledgeItemType.CONCEPT, title="Left", metadata={"workspace_id": scope.workspace_id})
    right = knowledge.create_item(item_type=KnowledgeItemType.EVIDENCE, title="Right", metadata={"workspace_id": scope.workspace_id})
    scope = scope.model_copy(update={"allowed_item_ids": sorted([left.item_id, right.item_id])})
    artifact = artifacts.put(draft_artifact(scope, proposals=[RelationProposal(proposal_id="p1", source_draft_or_item_id=left.item_id, target_draft_or_item_id=right.item_id, relation_type="supports", rationale="Evidence ev-a directly supports it.", evidence_ids=["ev-a"], confidence=0.9)]))
    receipt = commit.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="proposal-op", scope=scope)
    suggestion = suggestions.get(receipt.results[0].object_id)

    assert suggestion is not None
    assert suggestion.status is KnowledgeRelationSuggestionStatus.PENDING
    assert knowledge.list_relations() == []

    review = KnowledgeRelationSuggestionService(workspace=knowledge, repository=suggestions)
    accepted, relation = review.accept(suggestion.suggestion_id)
    replayed, same_relation = review.accept(suggestion.suggestion_id)
    assert accepted.status is KnowledgeRelationSuggestionStatus.ACCEPTED
    assert replayed.suggestion_id == accepted.suggestion_id
    assert same_relation.relation_id == relation.relation_id
    assert len(knowledge.list_relations()) == 1


def test_supports_proposal_without_evidence_is_not_committed(tmp_path):
    artifacts, knowledge, _, _, _, commit, scope = curator_stack(tmp_path)
    left = knowledge.create_item(item_type=KnowledgeItemType.CONCEPT, title="Left")
    right = knowledge.create_item(item_type=KnowledgeItemType.EVIDENCE, title="Right")
    scope = scope.model_copy(update={"allowed_item_ids": sorted([left.item_id, right.item_id])})
    artifact = artifacts.put(draft_artifact(scope, proposals=[RelationProposal(proposal_id="p1", source_draft_or_item_id=left.item_id, target_draft_or_item_id=right.item_id, relation_type="supports")]))
    receipt = commit.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="bad-support", scope=scope)
    assert receipt.status == "failed"
    assert "requires evidence" in receipt.results[0].message
