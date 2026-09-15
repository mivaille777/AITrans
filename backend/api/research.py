from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.dependencies import (
    get_research_note_service,
    get_research_workspace_service,
)
from backend.models.quick_actions import (
    ResearchNoteListItem,
    ResearchNoteListResponse,
    ResearchNoteSaveRequest,
    ResearchNoteSaveResponse,
)
from backend.models.research import (
    ResearchNoteDeleteResponse,
    ResearchNoteDetailResponse,
    ResearchNoteSearchResponse,
    ResearchNoteSearchResultResponse,
    ResearchNoteUpdateRequest,
    ResearchSourceProfileResponse,
    ResearchSourceSectionResponse,
    ResearchSourceSummaryResponse,
    ResearchWorkspaceCreateRequest,
    ResearchWorkspaceDeleteResponse,
    ResearchWorkspaceListResponse,
    ResearchWorkspaceMemberKind,
    ResearchWorkspaceMemberRequest,
    ResearchWorkspaceMemberResponse,
    ResearchWorkspaceProfileResponse,
    ResearchWorkspaceResponse,
    ResearchWorkspaceSummaryResponse,
    ResearchWorkspaceUpdateRequest,
)
from backend.services.research_note_service import ResearchNoteService, research_source_id
from backend.services.research_source_profile import ResearchSourceProfile, ResearchSourceSummary
from backend.services.research_workspace_service import (
    ResearchWorkspaceProfile,
    ResearchWorkspaceService,
)

router = APIRouter(prefix="/api/research", tags=["research"])
ResearchNoteServiceDependency = Annotated[
    ResearchNoteService,
    Depends(get_research_note_service),
]
ResearchWorkspaceServiceDependency = Annotated[
    ResearchWorkspaceService,
    Depends(get_research_workspace_service),
]


def _detail(note) -> ResearchNoteDetailResponse:
    return ResearchNoteDetailResponse(
        note_id=note.note_id,
        source_id=research_source_id(note),
        created_at=note.created_at,
        updated_at=note.updated_at,
        display_title=note.display_title,
        excerpt=note.excerpt,
        resource_url=note.resource_url,
        resource_title=note.resource_title,
        section_heading=note.section_heading,
        source_text=note.source_text,
        translated_text=note.translated_text,
        context_before=note.context_before,
        context_after=note.context_after,
        source_kind=note.source_kind,
        ai_content=note.ai_content,
        ai_action=note.ai_action,
        user_note=note.user_note,
        conversation_id=note.conversation_id,
    )


def _source_summary(item: ResearchSourceSummary) -> ResearchSourceSummaryResponse:
    return ResearchSourceSummaryResponse(
        source_id=item.source_id,
        display_title=item.display_title,
        resource_url=item.resource_url,
        resource_locator=item.resource_locator,
        source_kind=item.source_kind,
        source_family=item.source_family,
        identity_quality=item.identity_quality,
        note_count=item.note_count,
        section_count=item.section_count,
        linked_conversation_count=item.linked_conversation_count,
        annotation_count=item.annotation_count,
        ai_evidence_count=item.ai_evidence_count,
        updated_at=item.updated_at,
    )


def _source_profile(item: ResearchSourceProfile) -> ResearchSourceProfileResponse:
    return ResearchSourceProfileResponse(
        **_source_summary(item).model_dump(),
        sections=[
            ResearchSourceSectionResponse(
                section_id=section.section_id,
                heading=section.heading,
                note_count=section.note_count,
                linked_conversation_count=section.linked_conversation_count,
                annotation_count=section.annotation_count,
                ai_evidence_count=section.ai_evidence_count,
                updated_at=section.updated_at,
            )
            for section in item.sections
        ],
    )


def _workspace_summary(item: ResearchWorkspaceProfile) -> ResearchWorkspaceSummaryResponse:
    workspace = item.workspace
    return ResearchWorkspaceSummaryResponse(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        description=workspace.description,
        research_goal=workspace.research_goal,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        document_count=item.document_count,
        note_count=item.note_count,
        conversation_count=item.conversation_count,
    )


def _workspace_profile(item: ResearchWorkspaceProfile) -> ResearchWorkspaceProfileResponse:
    return ResearchWorkspaceProfileResponse(
        **_workspace_summary(item).model_dump(),
        document_ids=list(item.document_ids),
        note_ids=list(item.note_ids),
        conversation_ids=list(item.conversation_ids),
    )


def _workspace_member_operation(
    service: ResearchWorkspaceService,
    *,
    workspace_id: str,
    kind: ResearchWorkspaceMemberKind,
    resource_id: str,
    attach: bool,
) -> bool:
    operations = {
        ("document", True): service.attach_document,
        ("document", False): service.detach_document,
        ("note", True): service.attach_note,
        ("note", False): service.detach_note,
        ("conversation", True): service.attach_conversation,
        ("conversation", False): service.detach_conversation,
    }
    return operations[(kind, attach)](workspace_id, resource_id)


@router.get("/workspace", response_model=ResearchWorkspaceResponse)
def research_workspace(
    service: ResearchNoteServiceDependency,
    limit: int = Query(default=100, ge=1, le=100),
) -> ResearchWorkspaceResponse:
    notes = service.list_recent(limit=limit)
    sources = service.list_sources(limit=limit)
    return ResearchWorkspaceResponse(
        total=service.count(),
        sources=[_source_summary(item) for item in sources],
        notes=[_detail(note) for note in notes],
    )


@router.get("/workspaces", response_model=ResearchWorkspaceListResponse)
def list_research_workspaces(
    service: ResearchWorkspaceServiceDependency,
    limit: int = Query(default=50, ge=1, le=100),
) -> ResearchWorkspaceListResponse:
    items = service.list_recent(limit=limit)
    return ResearchWorkspaceListResponse(
        total=len(items),
        workspaces=[_workspace_summary(item) for item in items],
    )


@router.post(
    "/workspaces",
    response_model=ResearchWorkspaceProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_research_workspace(
    payload: ResearchWorkspaceCreateRequest,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceProfileResponse:
    try:
        return _workspace_profile(service.create(**payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}", response_model=ResearchWorkspaceProfileResponse)
def get_research_workspace(
    workspace_id: str,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceProfileResponse:
    item = service.get(workspace_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Research workspace not found.")
    return _workspace_profile(item)


@router.patch("/workspaces/{workspace_id}", response_model=ResearchWorkspaceProfileResponse)
def update_research_workspace(
    workspace_id: str,
    payload: ResearchWorkspaceUpdateRequest,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceProfileResponse:
    try:
        item = service.update(workspace_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Research workspace not found.")
    return _workspace_profile(item)


@router.delete("/workspaces/{workspace_id}", response_model=ResearchWorkspaceDeleteResponse)
def delete_research_workspace(
    workspace_id: str,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceDeleteResponse:
    return ResearchWorkspaceDeleteResponse(
        deleted=service.delete(workspace_id),
        workspace_id=workspace_id,
        resources_preserved=True,
    )


@router.post(
    "/workspaces/{workspace_id}/members/{kind}",
    response_model=ResearchWorkspaceMemberResponse,
)
def attach_research_workspace_member(
    workspace_id: str,
    kind: ResearchWorkspaceMemberKind,
    payload: ResearchWorkspaceMemberRequest,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceMemberResponse:
    if service.get(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Research workspace not found.")
    attached = _workspace_member_operation(
        service,
        workspace_id=workspace_id,
        kind=kind,
        resource_id=payload.resource_id,
        attach=True,
    )
    return ResearchWorkspaceMemberResponse(
        workspace_id=workspace_id,
        kind=kind,
        resource_id=payload.resource_id,
        attached=attached,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{kind}/{resource_id}",
    response_model=ResearchWorkspaceMemberResponse,
)
def detach_research_workspace_member(
    workspace_id: str,
    kind: ResearchWorkspaceMemberKind,
    resource_id: str,
    service: ResearchWorkspaceServiceDependency,
) -> ResearchWorkspaceMemberResponse:
    if service.get(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Research workspace not found.")
    detached = _workspace_member_operation(
        service,
        workspace_id=workspace_id,
        kind=kind,
        resource_id=resource_id,
        attach=False,
    )
    return ResearchWorkspaceMemberResponse(
        workspace_id=workspace_id,
        kind=kind,
        resource_id=resource_id,
        attached=not detached,
    )


@router.get("/search", response_model=ResearchNoteSearchResponse)
def search_research_memory(
    service: ResearchNoteServiceDependency,
    q: str = Query(min_length=1, max_length=4_000),
    limit: int = Query(default=8, ge=1, le=20),
    source_id: list[str] = Query(default=[]),
) -> ResearchNoteSearchResponse:
    try:
        matches = service.search(q, limit=limit, source_ids=source_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    results = [
        ResearchNoteSearchResultResponse(
            note_id=match.note.note_id,
            source_id=match.source_id,
            display_title=match.note.display_title,
            excerpt=(match.note.source_text or match.note.ai_content)[:1200].strip(),
            resource_url=match.note.resource_url,
            resource_title=match.note.resource_title,
            section_heading=match.note.section_heading,
            source_kind=match.note.source_kind,
            user_note=match.note.user_note[:1000].strip(),
            score=match.score,
        )
        for match in matches
    ]
    return ResearchNoteSearchResponse(query=q, count=len(results), results=results)


@router.get("/sources/{source_id}", response_model=ResearchSourceProfileResponse)
def get_research_source(
    source_id: str,
    service: ResearchNoteServiceDependency,
    limit: int = Query(default=100, ge=1, le=100),
) -> ResearchSourceProfileResponse:
    source = service.get_source(source_id, limit=limit)
    if source is None:
        raise HTTPException(status_code=404, detail="Research source not found.")
    return _source_profile(source)


@router.get("/notes", response_model=ResearchNoteListResponse)
def list_research_notes(
    service: ResearchNoteServiceDependency,
    limit: int = Query(default=5, ge=1, le=20),
) -> ResearchNoteListResponse:
    notes = service.list_recent(limit=limit)
    return ResearchNoteListResponse(
        total=service.count(),
        notes=[
            ResearchNoteListItem(
                note_id=note.note_id,
                display_title=note.display_title,
                excerpt=note.excerpt,
                updated_at=note.updated_at,
                resource_url=note.resource_url,
                resource_title=note.resource_title,
                section_heading=note.section_heading,
                source_text=note.source_text,
                translated_text=note.translated_text,
                context_before=note.context_before,
                context_after=note.context_after,
                source_kind=note.source_kind,
                ai_content=note.ai_content,
                ai_action=note.ai_action,
                conversation_id=getattr(note, "conversation_id", ""),
            )
            for note in notes
        ],
    )


@router.get("/notes/{note_id}", response_model=ResearchNoteDetailResponse)
def get_research_note(
    note_id: str,
    service: ResearchNoteServiceDependency,
) -> ResearchNoteDetailResponse:
    note = service.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Research note not found.")
    return _detail(note)


@router.patch("/notes/{note_id}", response_model=ResearchNoteDetailResponse)
def update_research_note(
    note_id: str,
    payload: ResearchNoteUpdateRequest,
    service: ResearchNoteServiceDependency,
) -> ResearchNoteDetailResponse:
    try:
        note = service.update_user_note(note_id, payload.user_note)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if note is None:
        raise HTTPException(status_code=404, detail="Research note not found.")
    return _detail(note)


@router.delete("/notes/{note_id}", response_model=ResearchNoteDeleteResponse)
def delete_research_note(
    note_id: str,
    service: ResearchNoteServiceDependency,
) -> ResearchNoteDeleteResponse:
    return ResearchNoteDeleteResponse(deleted=service.delete(note_id), note_id=note_id)


@router.post("/notes", response_model=ResearchNoteSaveResponse)
def save_research_note(
    payload: ResearchNoteSaveRequest,
    service: ResearchNoteServiceDependency,
) -> ResearchNoteSaveResponse:
    try:
        result = service.save(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    note = result.note
    return ResearchNoteSaveResponse(
        note_id=note.note_id,
        created=result.created,
        display_title=note.display_title,
        excerpt=note.excerpt,
        updated_at=note.updated_at,
        conversation_id=note.conversation_id,
    )
