from backend.models.agent_artifacts import KnowledgeItemDraft, NoteDraft
from tests.multi_agent._curator_support import curator_stack, draft_artifact


def test_cross_store_batch_reports_partial_failure_and_receipt_is_recoverable(tmp_path):
    artifacts, knowledge, _, notes, _, service, scope = curator_stack(tmp_path)
    artifact = artifacts.put(
        draft_artifact(
            scope,
            notes=[NoteDraft(draft_id="n1", source_id="paper-a", source_quote="quoted passage", ai_content="AI organization")],
            items=[KnowledgeItemDraft(draft_id="i1", item_type="insight", title="Unauthorized", source_ids=["paper-b"])],
        )
    )
    first = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="partial-op", scope=scope)
    recovered = service.get_receipt("partial-op")
    retried = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="partial-op", scope=scope)

    assert first.status == "partial"
    assert recovered is not None and recovered.status == "partial"
    assert retried.status == "partial"
    assert notes.count() == 1
    assert len([item for item in knowledge.list_items() if item.item_type.value == "note"]) == 1
    assert {item.status for item in retried.results} == {"committed", "failed"}


def test_stale_scope_cannot_replay_old_artifact(tmp_path):
    artifacts, _, _, _, _, service, scope = curator_stack(tmp_path)
    artifact = artifacts.put(draft_artifact(scope, items=[KnowledgeItemDraft(draft_id="i1", item_type="insight", title="One", source_ids=["paper-a"])]))
    changed_scope = type(scope).issue(scope_revision="curator-v2", workspace_id=scope.workspace_id, allowed_document_ids=[])
    try:
        service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="stale", scope=changed_scope)
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale artifact scope must be rejected")
