from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.agent_core.orchestration.artifact_store import SQLiteArtifactStore
from backend.api.writing_dependencies import get_writing_project_service
from backend.main import create_app
from backend.models.agent_artifacts import ManuscriptSectionArtifact, VerificationStatus
from backend.services.writing_project_service import WritingProjectService


def test_writing_api_persists_draft_and_exports_markdown(tmp_path: Path) -> None:
    path = tmp_path / "writing-api.sqlite3"
    store = SQLiteArtifactStore(path)
    service = WritingProjectService(artifact_store=store, database_path=path)
    section = store.put(
        ManuscriptSectionArtifact(
            artifact_id="api-section",
            producer_task_id="writer-api",
            scope_ref="scope-api",
            section_id="introduction",
            title="Introduction",
            markdown="A local draft.",
            paragraph_ids=["p1"],
            verification_status=VerificationStatus.PASSED,
        )
    )
    app = create_app()
    app.dependency_overrides[get_writing_project_service] = lambda: service
    client = TestClient(app)

    created_response = client.post(
        "/api/writing/projects",
        json={
            "workspace_id": "workspace-a",
            "title": "API manuscript",
            "writing_goal": "Keep revisions local.",
        },
    )
    assert created_response.status_code == 201
    project_id = created_response.json()["project_id"]

    saved_response = client.put(
        f"/api/writing/projects/{project_id}/sections",
        json={
            "artifact_id": section.artifact_id,
            "artifact_version": 1,
            "expected_version": 0,
        },
    )
    export_response = client.get(f"/api/writing/projects/{project_id}/export")
    list_response = client.get(
        "/api/writing/projects",
        params={"workspace_id": "workspace-a"},
    )

    assert saved_response.status_code == 200
    assert saved_response.json()["version"] == 1
    assert export_response.status_code == 200
    assert "# API manuscript" in export_response.json()["markdown"]
    assert "A local draft." in export_response.json()["markdown"]
    assert list_response.json()["total"] == 1


def test_writing_api_returns_conflict_for_stale_section_version(tmp_path: Path) -> None:
    path = tmp_path / "writing-api-conflict.sqlite3"
    store = SQLiteArtifactStore(path)
    service = WritingProjectService(artifact_store=store, database_path=path)
    project = service.create(workspace_id="workspace-a", title="Conflict")
    section = store.put(
        ManuscriptSectionArtifact(
            artifact_id="api-conflict-section",
            producer_task_id="writer-api",
            scope_ref="scope-api",
            section_id="discussion",
            markdown="Version one.",
            paragraph_ids=["p1"],
        )
    )
    service.save_section(
        project.project_id,
        artifact_id=section.artifact_id,
        artifact_version=1,
        expected_version=0,
    )
    app = create_app()
    app.dependency_overrides[get_writing_project_service] = lambda: service
    client = TestClient(app)

    response = client.put(
        f"/api/writing/projects/{project.project_id}/sections",
        json={
            "artifact_id": section.artifact_id,
            "artifact_version": 1,
            "expected_version": 0,
        },
    )

    assert response.status_code == 409
    assert "section version conflict" in response.json()["detail"]
