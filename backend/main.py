from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.agent import router as agent_router
from backend.api.agent_checkpoint_dependencies import close_agent_checkpoint_service
from backend.api.agent_knowledge import router as agent_knowledge_router
from backend.api.agent_observability import router as agent_observability_router
from backend.api.agent_routing import router as agent_routing_router
from backend.api.agent_runtime_config import router as agent_runtime_config_router
from backend.api.browser_context import router as browser_context_router
from backend.api.companion import router as companion_router
from backend.api.companion_stream import router as companion_stream_router
from backend.api.conversations import router as conversations_router
from backend.api.curator import router as curator_router
from backend.api.curator_dependencies import close_curator_commit_service
from backend.api.evidence_ledger import router as evidence_ledger_router
from backend.api.evidence_review import router as evidence_review_router
from backend.api.health import router as health_router
from backend.api.knowledge import router as knowledge_router
from backend.api.knowledge_boards import router as knowledge_boards_router
from backend.api.knowledge_canvas import router as knowledge_canvas_router
from backend.api.knowledge_items import router as knowledge_items_router
from backend.api.knowledge_preview import router as knowledge_preview_router
from backend.api.knowledge_relation_suggestions import (
    router as knowledge_relation_suggestions_router,
)
from backend.api.knowledge_relations import router as knowledge_relations_router
from backend.api.llm_settings import router as llm_settings_router
from backend.api.overlay import router as overlay_router
from backend.api.quick_actions import router as quick_actions_router
from backend.api.rag_models import router as rag_models_router
from backend.api.reading import router as reading_router
from backend.api.research import router as research_router
from backend.api.research_memory import router as research_memory_router
from backend.api.routes.knowledge_v2 import router as knowledge_v2_router
from backend.api.translation import router as translation_router
from backend.api.translation_cascade import router as translation_cascade_router
from backend.api.writing import router as writing_router
from backend.core.middleware import RequestLoggingMiddleware

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8766


class AITranslatorFastAPI(FastAPI):
    """Keep route introspection flat across FastAPI's nested-router transition."""

    @property
    def routes(self):
        flattened = []

        def collect(routes):
            for route in routes:
                included = getattr(route, "original_router", None)
                if included is None:
                    flattened.append(route)
                else:
                    collect(included.routes)

        collect(self.router.routes)
        return flattened


def get_dev_origins():
    origins = list(DEV_ORIGINS)
    configured_origin = os.getenv("AITRANS_FRONTEND_ORIGIN", "").strip().rstrip("/")
    if configured_origin and configured_origin not in origins:
        origins.append(configured_origin)
    return origins


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        close_curator_commit_service()
        close_agent_checkpoint_service()


def create_app():
    app = AITranslatorFastAPI(
        title="AITranslator API", version="0.18.0", lifespan=lifespan
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_dev_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    routers = [
        health_router,
        knowledge_router,
        knowledge_v2_router,
        knowledge_canvas_router,
        agent_router,
        agent_knowledge_router,
        agent_routing_router,
        agent_observability_router,
        agent_runtime_config_router,
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
        knowledge_preview_router,
        knowledge_items_router,
        knowledge_boards_router,
        knowledge_relations_router,
        knowledge_relation_suggestions_router,
        llm_settings_router,
        rag_models_router,
        companion_router,
        companion_stream_router,
        conversations_router,
        writing_router,
        curator_router,
    ]
    for router in routers:
        app.include_router(router)

    return app


app = create_app()


def main():
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("AITRANS_API_HOST", DEFAULT_API_HOST),
        port=int(os.getenv("AITRANS_API_PORT", str(DEFAULT_API_PORT))),
        reload=False,
    )


if __name__ == "__main__":
    main()
