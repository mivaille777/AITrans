from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.writing_dependencies import get_writing_project_service
from backend.models.writing_projects import (
    WritingArtifactSaveRequest,
    WritingExportResponse,
    WritingOperationReceipt,
    WritingProjectCreateRequest,
    WritingProjectListResponse,
    WritingProjectSnapshot,
    WritingRevisionApplyRequest,
    WritingRevisionPreviewRequest,
    WritingRevisionPreviewResponse,
    WritingSectionSnapshot,
)
from backend.services.writing_project_service import (
    WritingProjectConflictError,
    WritingProjectError,
    WritingProjectService,
)

router = APIRouter(prefix="/api/writing", tags=["academic-writing"])
WritingProjectDependency = Annotated[
    WritingProjectService,
    Depends(get_writing_project_service),
]


def _raise(exc: Exception) -> None:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, WritingProjectConflictError)
        else status.HTTP_404_NOT_FOUND
        if "not found" in str(exc).casefold()
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post(
    "/projects",
    response_model=WritingProjectSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def create_writing_project(
    payload: WritingProjectCreateRequest,
    service: WritingProjectDependency,
) -> WritingProjectSnapshot:
    try:
        return service.create(**payload.model_dump())
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.get("/projects", response_model=WritingProjectListResponse)
def list_writing_projects(
    service: WritingProjectDependency,
    workspace_id: str = Query(default="", max_length=256),
    limit: int = Query(default=100, ge=1, le=500),
) -> WritingProjectListResponse:
    projects = service.list(workspace_id=workspace_id, limit=limit)
    return WritingProjectListResponse(total=len(projects), projects=list(projects))


@router.get("/projects/{project_id}", response_model=WritingProjectSnapshot)
def get_writing_project(
    project_id: str,
    service: WritingProjectDependency,
) -> WritingProjectSnapshot:
    project = service.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Writing project not found")
    return project


@router.put("/projects/{project_id}/outline", response_model=WritingProjectSnapshot)
def save_writing_outline(
    project_id: str,
    payload: WritingArtifactSaveRequest,
    service: WritingProjectDependency,
) -> WritingProjectSnapshot:
    try:
        return service.save_outline(project_id, **payload.model_dump())
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.put(
    "/projects/{project_id}/sections",
    response_model=WritingSectionSnapshot,
)
def save_writing_section(
    project_id: str,
    payload: WritingArtifactSaveRequest,
    service: WritingProjectDependency,
) -> WritingSectionSnapshot:
    try:
        return service.save_section(project_id, **payload.model_dump())
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.post(
    "/projects/{project_id}/sections/{section_id}/revision-preview",
    response_model=WritingRevisionPreviewResponse,
)
def preview_writing_revision(
    project_id: str,
    section_id: str,
    payload: WritingRevisionPreviewRequest,
    service: WritingProjectDependency,
) -> WritingRevisionPreviewResponse:
    try:
        return service.prepare_revision(project_id, section_id, payload)
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.post(
    "/projects/{project_id}/revisions/apply",
    response_model=WritingOperationReceipt,
)
def apply_writing_revision(
    project_id: str,
    payload: WritingRevisionApplyRequest,
    service: WritingProjectDependency,
) -> WritingOperationReceipt:
    try:
        return service.apply_revision(project_id, **payload.model_dump())
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


@router.get("/projects/{project_id}/export", response_model=WritingExportResponse)
def export_writing_project(
    project_id: str,
    service: WritingProjectDependency,
) -> WritingExportResponse:
    try:
        return service.export_markdown(project_id)
    except WritingProjectError as exc:
        _raise(exc)
        raise AssertionError("unreachable")


__all__ = ["router"]
