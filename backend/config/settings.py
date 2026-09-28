"""Application-wide configuration.

This module intentionally keeps configuration lightweight and compatible with
AITranslator's existing backend layout. Runtime modules can gradually migrate
to this single configuration entry point.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.paths import data_root, is_frozen_application, logs_dir


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_DIR = data_root() if is_frozen_application() else PROJECT_ROOT


@dataclass(frozen=True)
class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8766"))

    ROOT_DIR: Path = ROOT_DIR
    RUNTIME_DIR: Path = ROOT_DIR / "runtime"
    LOG_DIR: Path = logs_dir()

    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        str(ROOT_DIR / "data" / "aitrans.db"),
    )

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "")

    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))


settings = Settings()

settings.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
