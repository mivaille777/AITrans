from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent_core.orchestration.artifact_store import SQLiteArtifactStore
from backend.models.agent_artifacts import (
    EvidenceRef,
    ManuscriptSectionArtifact,
    OutlineArtifact,
    OutlineSection,
    ReferenceRecord,
    VerificationStatus,
)
from backend.services.writing_project_service import (
    WritingProjectConflictError,
    WritingProjectService,
)


class Workspaces:
    def get(self, workspace_id: str):
        return object() if workspace_id == "workspace-a" else None


def build_service(path: Path) -> tuple[SQLiteArtifactStore, WritingProjectService]:
    store = SQLiteArtifactStore(path)
    return store, WritingProjectService(
        artifact_store=store,
        database_path=path,
        workspace_service=Workspaces(),
    )


def test_writing_project_persists_outline_and_section_versions(tmp_path: Path) -> None:
    path = tmp_path / "agent-artifacts.sqlite3"
    store, service = build_service(path)
    project = service.create(
        workspace_id="workspace-a",
        title="Control survey",
        writing_goal="Prepare a bounded literature review.",
    )
    outline = store.put(
        OutlineArtifact(
            artifact_id="outline-a",
            producer_task_id="writer-1",
            scope_ref="scope-a",
            title="Control survey",
            sections=[
                OutlineSection(
                    section_id="related-work",
                    title="Related Work",
                    objective="Compare reviewed control methods.",
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
    with_outline = service.save_outline(
        project.project_id,
        artifact_id=outline.artifact_id,
        artifact_version=outline.version,
        expected_version=0,
    )
    section = store.put(
        ManuscriptSectionArtifact(
            artifact_id="section-related-work",
            producer_task_id="writer-2",
            scope_ref="scope-a",
            section_id="related-work",
            title="Related Work",
            markdown="Paper A establishes bounded adaptation [1].",
            paragraph_ids=["p1"],
            claim_source_map={"p1": ["ev-a"]},
            references=[
                ReferenceRecord(
                    source_id="paper-a",
                    title="Paper A",
                    evidence_ids=["ev-a"],
                    missing_fields=["authors", "year", "doi"],
                )
            ],
            evidence_refs=list(outline.evidence_refs),
            verification_status=VerificationStatus.PASSED,
        )
    )
    saved = service.save_section(
        project.project_id,
        artifact_id=section.artifact_id,
        artifact_version=section.version,
        expected_version=0,
    )

    reopened_store, reopened = build_service(path)
    restored = reopened.get(project.project_id)

    assert reopened_store.get(outline.artifact_id, 1) is not None
    assert with_outline.outline_version == 1
    assert saved.version == 1
    assert restored is not None
    assert restored.title == "Control survey"
    assert restored.outline_ref == outline.ref()
    assert restored.sections[0].paragraphs[0].paragraph_id == "p1"
    assert restored.sections[0].artifact_ref == section.ref()


def test_writing_project_uses_optimistic_versions(tmp_path: Path) -> None:
    path = tmp_path / "agent-artifacts.sqlite3"
    store, service = build_service(path)
    project = service.create(workspace_id="workspace-a", title="Draft")
    outline = store.put(
        OutlineArtifact(
            artifact_id="outline-conflict",
            producer_task_id="writer",
            scope_ref="scope",
            title="Draft",
        )
    )
    service.save_outline(
        project.project_id,
        artifact_id=outline.artifact_id,
        artifact_version=1,
        expected_version=0,
    )

    with pytest.raises(WritingProjectConflictError, match="outline version conflict"):
        service.save_outline(
            project.project_id,
            artifact_id=outline.artifact_id,
            artifact_version=1,
            expected_version=0,
        )
