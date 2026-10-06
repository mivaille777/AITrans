"""Shared metadata cache and storage; activation sessions are never shared."""

from functools import lru_cache
from pathlib import Path

from app.infrastructure.paths import data_root
from backend.services.skill_runtime import SkillRuntime
from backend.services.skill_service import SkillService


@lru_cache(maxsize=1)
def get_skill_service() -> SkillService:
    return SkillService(Path(data_root()) / "data" / "skills")


@lru_cache(maxsize=1)
def get_skill_runtime() -> SkillRuntime:
    return SkillRuntime(get_skill_service())
