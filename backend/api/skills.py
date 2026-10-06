import logging
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.models.skills import (
    CreateSkillRequest,
    ImportSkillRequest,
    SetSkillEnabledRequest,
    SkillCatalog,
    SkillDetail,
    SkillFileContent,
    SkillLibrary,
    SkillRoutePreview,
    SkillRouteRequest,
    WriteSkillFileRequest,
)
from backend.services.skill_dependencies import get_skill_service
from backend.services.skill_runtime import SkillRuntime
from backend.services.skill_service import SkillError, SkillService

router = APIRouter(prefix="/api/skills", tags=["skills"])


Service = Annotated[SkillService, Depends(get_skill_service)]
T = TypeVar("T")


def _call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except SkillError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from exc
    except OSError as exc:
        logging.getLogger(__name__).exception("Skill filesystem operation failed")
        raise HTTPException(
            500, detail="无法读写技能文件，请检查目录权限后重试。"
        ) from exc


@router.get("", response_model=SkillLibrary)
def list_skills(service: Service):
    return _call(service.list)


@router.post("", response_model=SkillDetail, status_code=201)
def create_skill(payload: CreateSkillRequest, service: Service):
    return _call(lambda: service.create(payload.name, payload.description))


@router.post("/import", response_model=SkillDetail, status_code=201)
def import_skill(payload: ImportSkillRequest, service: Service):
    return _call(
        lambda: service.import_skill(path=payload.path, content=payload.content)
    )


@router.get("/catalog", response_model=SkillCatalog)
def skill_catalog(
    service: Service,
    context_mode: str = Query(default="general", pattern="^(general|reading)$"),
):
    return _call(lambda: SkillRuntime(service).catalog(context_mode))


@router.post("/route", response_model=SkillRoutePreview)
def preview_skill_route(payload: SkillRouteRequest, service: Service):
    return _call(
        lambda: SkillRuntime(service).route(
            payload.query, payload.context_mode, payload.category
        )
    )


@router.get("/{skill_id}", response_model=SkillDetail)
def get_skill(skill_id: str, service: Service):
    return _call(lambda: service.detail(skill_id))


@router.patch("/{skill_id}", response_model=SkillDetail)
def set_skill_enabled(skill_id: str, payload: SetSkillEnabledRequest, service: Service):
    return _call(lambda: service.set_enabled(skill_id, payload.enabled))


@router.delete("/{skill_id}")
def remove_skill(skill_id: str, service: Service):
    return {"removed": True, "archived_path": _call(lambda: service.remove(skill_id))}


@router.get("/{skill_id}/file", response_model=SkillFileContent)
def read_skill_file(
    skill_id: str, service: Service, path: str = Query(min_length=1, max_length=1024)
):
    return _call(lambda: service.read_file(skill_id, path))


@router.put("/{skill_id}/file", response_model=SkillFileContent)
def write_skill_file(skill_id: str, payload: WriteSkillFileRequest, service: Service):
    return _call(
        lambda: service.write_file(
            skill_id, payload.path, payload.content, payload.revision
        )
    )


@router.delete("/{skill_id}/file")
def delete_skill_file(
    skill_id: str,
    service: Service,
    path: str = Query(min_length=1, max_length=1024),
    revision: str = Query(pattern=r"^[a-f0-9]{64}$"),
):
    _call(lambda: service.delete_file(skill_id, path, revision))
    return {"removed": True}
