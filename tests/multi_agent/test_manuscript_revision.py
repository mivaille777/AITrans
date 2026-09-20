from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent_core.orchestration.artifact_store import SQLiteArtifactStore
from backend.models.agent_artifacts import (
    EvidenceRef,
    ManuscriptSectionArtifact,
    VerificationStatus,
)
from backend.models.writing_projects import (
    WritingRevisionChangeRequest,
    WritingRevisionPreviewRequest,
)
from backend.services.writing_project_service import (
    WritingProjectConflictError,
    WritingProjectError,
    WritingProjectService,
)


def setup_project(tmp_path: Path):
    path = tmp_path / "artifacts.sqlite3"
    store = SQLiteArtifactStore(path)
    service = WritingProjectService(artifact_store=store, database_path=path)
    project = service.create(workspace_id="workspace-a", title="Revision test")
    base = store.put(
        ManuscriptSectionArtifact(
            artifact_id="section-introduction",
            producer_task_id="writer-1",
            scope_ref="scope-a",
            section_id="introduction",
            title="Introduction",
            markdown="Paragraph one.\n\nParagraph two.\n\nParagraph three.",
            paragraph_ids=["p1", "p2", "p3"],
            claim_source_map={"p1": ["ev-a"], "p2": [], "p3": ["ev-a"]},
            evidence_refs=[
                EvidenceRef(
                    evidence_id="ev-a",
                    source_id="paper-a",
                    source_type="document_chunk",
                )
            ],
            verification_status=VerificationStatus.PASSED,
        )
    )
    service.save_section(
        project.project_id,
        artifact_id=base.artifact_id,
        artifact_version=base.version,
        expected_version=0,
    )
    return store, service, project


def test_local_revision_preview_and_apply_preserve_unselected_paragraphs(tmp_path: Path) -> None:
    store, service, project = setup_project(tmp_path)
    before = service.get(project.project_id)
    assert before is not None
    hashes = {
        item.paragraph_id: item.content_hash for item in before.sections[0].paragraphs
    }
    preview = service.prepare_revision(
        project.project_id,
        "introduction",
        WritingRevisionPreviewRequest(
            expected_version=1,
            changes=[
                WritingRevisionChangeRequest(
                    paragraph_id="p2",
                    replacement_markdown="Revised paragraph two.",
                    rationale="Improve clarity.",
                    category="suggestion",
                )
            ],
        ),
    )

    # Preview/cancel does not mutate the selected manuscript version.
    unchanged = service.get(project.project_id)
    assert unchanged is not None
    assert unchanged.sections[0].version == 1
    assert unchanged.sections[0].paragraphs[1].markdown == "Paragraph two."

    receipt = service.apply_revision(
        project.project_id,
        artifact_id=preview.revision_ref.artifact_id,
        artifact_version=preview.revision_ref.version,
        expected_version=1,
        operation_id="apply-p2-v1",
    )
    updated = service.get(project.project_id)

    assert receipt.result_version == 2
    assert updated is not None
    paragraphs = {item.paragraph_id: item for item in updated.sections[0].paragraphs}
    assert paragraphs["p1"].content_hash == hashes["p1"]
    assert paragraphs["p3"].content_hash == hashes["p3"]
    assert paragraphs["p2"].markdown == "Revised paragraph two."
    assert paragraphs["p2"].content_hash != hashes["p2"]
    stored = store.get(receipt.artifact_ref.artifact_id, receipt.artifact_ref.version)
    assert isinstance(stored, ManuscriptSectionArtifact)
    assert [item.artifact_id for item in stored.lineage] == [
        "section-introduction",
        preview.revision_ref.artifact_id,
    ]

    replay = service.apply_revision(
        project.project_id,
        artifact_id=preview.revision_ref.artifact_id,
        artifact_version=preview.revision_ref.version,
        expected_version=1,
        operation_id="apply-p2-v1",
    )
    assert replay.replayed is True
    assert replay.artifact_ref == receipt.artifact_ref


def test_revision_rejects_stale_version_and_unauthorized_paragraph(tmp_path: Path) -> None:
    _store, service, project = setup_project(tmp_path)

    with pytest.raises(WritingProjectError, match="unknown paragraph"):
        service.prepare_revision(
            project.project_id,
            "introduction",
            WritingRevisionPreviewRequest(
                expected_version=1,
                changes=[
                    WritingRevisionChangeRequest(
                        paragraph_id="p9",
                        replacement_markdown="Out of scope.",
                    )
                ],
            ),
        )

    with pytest.raises(WritingProjectConflictError, match="version conflict"):
        service.prepare_revision(
            project.project_id,
            "introduction",
            WritingRevisionPreviewRequest(
                expected_version=2,
                changes=[
                    WritingRevisionChangeRequest(
                        paragraph_id="p2",
                        replacement_markdown="Stale edit.",
                    )
                ],
            ),
        )


def test_factual_revision_requires_known_evidence(tmp_path: Path) -> None:
    _store, service, project = setup_project(tmp_path)

    with pytest.raises(WritingProjectError, match="requires evidence"):
        service.prepare_revision(
            project.project_id,
            "introduction",
            WritingRevisionPreviewRequest(
                expected_version=1,
                changes=[
                    WritingRevisionChangeRequest(
                        paragraph_id="p2",
                        replacement_markdown="A new factual claim.",
                        category="fact",
                    )
                ],
            ),
        )
