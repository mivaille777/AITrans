from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.middleware import RequestLoggingMiddleware
from backend.api.knowledge_v2 import router as knowledge_v2_router

# Existing routers remain unchanged
from backend.api.agent import router as agent_router
from backend.api.health import router as health_router

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8766


def get_dev_origins():
    origins = list(DEV_ORIGINS)
    configured_origin = os.getenv("AITRANS_FRONTEND_ORIGIN", "").strip().rstrip("/")
    if configured_origin and configured_origin not in origins:
        origins.append(configured_origin)
    return origins


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


def create_app():
    app = FastAPI(
        title="AITranslator API",
        version="0.18.0",
        description="Local API boundary for the AITranslator WebReBuild desktop client.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_dev_origins(),
        allow_origin_regex=r"^https?://(localhost|127\\.0\\.1)(:\\d+)?$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(agent_router)

    # Knowledge 2.0 API boundary
    app.include_router(knowledge_v2_router)

    return app


app = create_app()


def main():
    import uvicorn
    host = os.getenv("AITRANS_API_HOST", DEFAULT_API_HOST)
    port = int(os.getenv("AITRANS_API_PORT", str(DEFAULT_API_PORT)))
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
