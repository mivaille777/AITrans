from backend.models.agent_artifacts import NoteDraft
from backend.services.curator_commit_service import research_note_content_hash
from tests.multi_agent._curator_support import curator_stack, draft_artifact


def test_curator_updates_ai_content_without_overwriting_user_note(tmp_path):
    artifacts, knowledge, _, notes, _, service, scope = curator_stack(tmp_path)
    original = notes.save(
        source_text="Exact source quote.",
        resource_title="Paper A",
        source_kind="agent_curator",
        ai_content="Old AI summary",
        user_note="Keep my private interpretation",
        workspace_id=scope.workspace_id,
    ).note
    artifact = artifacts.put(
        draft_artifact(
            scope,
            notes=[
                NoteDraft(
                    draft_id="note-a",
                    source_id="paper-a",
                    source_quote=original.source_text,
                    ai_content="Updated AI summary",
                    resource_title=original.resource_title,
                    existing_note_id=original.note_id,
                    expected_version=1,
                    expected_content_hash=research_note_content_hash(original),
                )
            ],
        )
    )
    receipt = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="preserve-note", scope=scope)
    saved = notes.get(original.note_id)

    assert receipt.status == "completed"
    assert saved is not None
    assert saved.source_text == "Exact source quote."
    assert saved.ai_content == "Updated AI summary"
    assert saved.user_note == "Keep my private interpretation"
    linked = [item for item in knowledge.list_items() if item.metadata.get("research_note_id") == original.note_id]
    assert len(linked) == 1


def test_ai_draft_cannot_write_user_note(tmp_path):
    artifacts, _, _, _, _, service, scope = curator_stack(tmp_path)
    artifact = artifacts.put(draft_artifact(scope, notes=[NoteDraft(draft_id="n", source_id="paper-a", source_quote="quote", ai_content="summary", user_note="model-owned")]))
    receipt = service.apply(artifact_id=artifact.artifact_id, artifact_version=1, operation_id="reject-user-note", scope=scope)
    assert receipt.status == "failed"
    assert "cannot write user_note" in receipt.results[0].message
