from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.middleware import RequestLoggingMiddleware

from backend.api.agent import router as agent_router
from backend.api.agent_observability import router as agent_observability_router
from backend.api.agent_runtime_config import router as agent_runtime_config_router
from backend.api.browser_context import router as browser_context_router
from backend.api.companion import router as companion_router
from backend.api.companion_stream import router as companion_stream_router
from backend.api.conversations import router as conversations_router
from backend.api.evidence_ledger import router as evidence_ledger_router
from backend.api.evidence_review import router as evidence_review_router
from backend.api.health import router as health_router
from backend.api.knowledge import router as knowledge_router
from backend.api.knowledge_boards import router as knowledge_boards_router
from backend.api.knowledge_items import router as knowledge_items_router
from backend.api.knowledge_preview import router as knowledge_preview_router
from backend.api.knowledge_relation_suggestions import router as knowledge_relation_suggestions_router
from backend.api.knowledge_relations import router as knowledge_relations_router
from backend.api.llm_settings import router as llm_settings_router
from backend.api.overlay import router as overlay_router
from backend.api.quick_actions import router as quick_actions_router
from backend.api.rag_models import router as rag_models_router
from backend.api.reading import router as reading_router
from backend.api.research import router as research_router
from backend.api.research_memory import router as research_memory_router
from backend.api.translation import router as translation_router
from backend.api.translation_cascade import router as translation_cascade_router

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

    for router in [
        health_router,
        translation_router,
        translation_cascade_router,
        browser_context_router,
        reading_router,
        overlay_router,
        quick_actions_router,
        research_router,
        research_memory_router,
        evidence_ledger_router,
        evidence_review_router,
        knowledge_router,
        knowledge_preview_router,
        knowledge_items_router,
        knowledge_boards_router,
        knowledge_relations_router,
        knowledge_relation_suggestions_router,
        llm_settings_router,
        rag_models_router,
        agent_router,
        agent_observability_router,
        agent_runtime_config_router,
        companion_router,
        companion_stream_router,
        conversations_router,
    ]:
        app.include_router(router)

    return app


app = create_app()


def main():
    import uvicorn
    host = os.getenv("AITRANS_API_HOST", DEFAULT_API_HOST)
    port = int(os.getenv("AITRANS_API_PORT", str(DEFAULT_API_PORT)))
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
