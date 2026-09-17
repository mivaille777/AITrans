from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.agent_core.orchestration.artifact_store import SQLiteArtifactStore
from backend.models.agent_artifacts import (
    EvidenceRef,
    ManuscriptSectionArtifact,
    OutlineArtifact,
    OutlineSection,
    ReferenceRecord,
    VerificationStatus,
)
from backend.services.writing_project_service import WritingProjectService


def test_markdown_export_uses_selected_versions_and_source_metadata(tmp_path: Path) -> None:
    path = tmp_path / "artifacts.sqlite3"
    store = SQLiteArtifactStore(path)
    service = WritingProjectService(artifact_store=store, database_path=path)
    project = service.create(
        workspace_id="workspace-a",
        title="Verified manuscript",
        writing_goal="Explain bounded adaptation.",
    )
    outline = store.put(
        OutlineArtifact(
            artifact_id="export-outline",
            producer_task_id="writer-1",
            scope_ref="scope-a",
            title="Verified manuscript",
            sections=[
                OutlineSection(
                    section_id="discussion",
                    title="Discussion",
                    objective="Discuss the supported finding.",
                )
            ],
        )
    )
    service.save_outline(
        project.project_id,
        artifact_id=outline.artifact_id,
        artifact_version=1,
        expected_version=0,
    )
    section = store.put(
        ManuscriptSectionArtifact(
            artifact_id="export-section",
            producer_task_id="writer-2",
            scope_ref="scope-a",
            section_id="discussion",
            title="Discussion",
            markdown="Bounded adaptation is supported by the reviewed source [1].",
            paragraph_ids=["discussion-p1"],
            claim_source_map={"discussion-p1": ["ev-a"]},
            references=[
                ReferenceRecord(
                    source_id="paper-a",
                    title="Bounded Adaptation",
                    authors=["A. Researcher"],
                    year="2025",
                    doi="10.1000/example",
                    evidence_ids=["ev-a"],
                )
            ],
            evidence_refs=[
                EvidenceRef(
                    evidence_id="ev-a",
                    source_id="paper-a",
                    source_type="review_ledger",
                )
            ],
            verification_status=VerificationStatus.PASSED,
        )
    )
    service.save_section(
        project.project_id,
        artifact_id=section.artifact_id,
        artifact_version=1,
        expected_version=0,
    )

    exported = service.export_markdown(project.project_id)

    assert exported.outline_version == 1
    assert exported.section_versions == {"discussion": 1}
    assert "# Verified manuscript" in exported.markdown
    assert "## Outline" in exported.markdown
    assert "## Discussion" in exported.markdown
    assert "Bounded Adaptation — A. Researcher, 2025, 10.1000/example" in exported.markdown
    assert exported.references[0].doi == "10.1000/example"
    assert exported.source_statuses == {"paper-a": "legacy_unknown"}
    assert exported.verification_status == "unverified_currentness"


def test_export_marks_changed_source_stale_and_requires_revalidation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts.sqlite3"
    store = SQLiteArtifactStore(path)

    class Workspace:
        @staticmethod
        def get(workspace_id: str):
            assert workspace_id == "workspace-a"
            return SimpleNamespace(document_ids=("paper-a",), note_ids=())

    class Library:
        @staticmethod
        def get_document(document_id: str):
            assert document_id == "paper-a"
            return SimpleNamespace(content_hash="new-source-hash")

    service = WritingProjectService(
        artifact_store=store,
        database_path=path,
        workspace_service=Workspace(),
        knowledge_library=Library(),
    )
    project = service.create(workspace_id="workspace-a", title="Stale manuscript")
    section = store.put(
        ManuscriptSectionArtifact(
            artifact_id="stale-section",
            producer_task_id="writer-1",
            scope_ref="scope-a",
            section_id="discussion",
            title="Discussion",
            markdown="An old source supported this sentence [1].",
            paragraph_ids=["discussion-p1"],
            claim_source_map={"discussion-p1": ["ev-a"]},
            references=[
                ReferenceRecord(
                    source_id="paper-a",
                    title="Changed paper",
                    evidence_ids=["ev-a"],
                )
            ],
            evidence_refs=[
                EvidenceRef(
                    evidence_id="ev-a",
                    source_id="paper-a",
                    source_type="document_chunk",
                    source_hash="captured-old-hash",
                )
            ],
            verification_status=VerificationStatus.PASSED,
        )
    )
    service.save_section(
        project.project_id,
        artifact_id=section.artifact_id,
        artifact_version=1,
        expected_version=0,
    )

    exported = service.export_markdown(project.project_id)

    assert exported.source_statuses == {"paper-a": "stale"}
    assert exported.verification_status == "requires_revalidation"
    assert exported.warnings == [
        "Source paper-a is stale; revalidate affected claims before reuse."
    ]
    assert "[source status: stale]" in exported.markdown
    assert "## Revalidation required" in exported.markdown
