from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any

from qdrant_client import QdrantClient

from app.infrastructure.paths import data_root
from app.infrastructure.settings import SettingsManager
from backend.api.rag_model_dependencies import get_rag_model_manager
from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import (
    RagConfig,
    RagVisualRetrievalConfig,
    RagVisualUnderstandingConfig,
)
from backend.rag.embeddings import EmbeddingProvider, create_embedding_provider
from backend.rag.index_manifest import IndexManifest
from backend.rag.index_service import IndexService
from backend.rag.parsers import parse_document
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.semantic_chunking import SemanticStructureAwareChunker
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores import QdrantLocalVectorStore
from backend.rag.vision import (
    VisualDescriptionProvider,
    create_visual_description_provider,
)
from backend.rag.visual_adaptive import (
    AdaptiveVisualRetrievalService,
    create_adaptive_visual_vector_store,
)
from backend.rag.visual_retrieval import (
    QdrantVisualMultiVectorStore,
    VisualAwareIndexService,
    VisualEmbeddingProvider,
    VisualIndexCoordinator,
    VisualRetrievalService,
    create_visual_embedding_provider,
)
from backend.services.knowledge_library_service import (
    DEFAULT_KNOWLEDGE_MAX_FILE_BYTES,
    KnowledgeLibraryService,
)


@dataclass(slots=True)
class RagRuntime:
    config: RagConfig
    embedding_provider: EmbeddingProvider
    vector_store: QdrantLocalVectorStore
    sparse_retriever: BM25SparseRetriever
    manifest: IndexManifest
    retrieval_service: RetrievalService | VisualRetrievalService
    index_service: IndexService | VisualAwareIndexService
    library_service: KnowledgeLibraryService
    visual_description_provider: VisualDescriptionProvider | None = None
    visual_embedding_provider: VisualEmbeddingProvider | None = None
    visual_vector_store: QdrantVisualMultiVectorStore | None = None
    shared_qdrant_client: QdrantClient | None = None


_runtime: RagRuntime | None = None
_runtime_lock = Lock()


def _allowed_roots() -> tuple[Path, ...]:
    configured = os.getenv("AITRANS_KNOWLEDGE_ALLOWED_ROOTS", "").strip()
    if not configured:
        return (Path.home().resolve(),)
    roots = tuple(
        Path(item).expanduser().resolve()
        for item in configured.split(os.pathsep)
        if item.strip()
    )
    return roots or (Path.home().resolve(),)


def _max_file_bytes() -> int:
    configured = os.getenv("AITRANS_KNOWLEDGE_MAX_FILE_BYTES", "").strip()
    try:
        return max(1, int(configured)) if configured else DEFAULT_KNOWLEDGE_MAX_FILE_BYTES
    except ValueError:
        return DEFAULT_KNOWLEDGE_MAX_FILE_BYTES


def _resolve_runtime_storage_path(configured_path: str | Path) -> Path:
    candidate = Path(configured_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (data_root() / candidate).resolve()


def _build_document_parser(config: RagConfig):
    advanced_config = config.advanced_parsing.model_copy(deep=True)
    return partial(parse_document, advanced_config=advanced_config)


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name, "").strip().casefold()
    if not value:
        return None
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_visual_understanding_config(
    config: RagVisualUnderstandingConfig,
    settings: dict[str, Any],
) -> RagVisualUnderstandingConfig:
    """Resolve optional VLM settings without coupling RAG to the chat provider."""

    updates: dict[str, Any] = {}
    env_enabled = _env_bool("AITRANS_RAG_VLM_ENABLED")
    if env_enabled is not None:
        updates["enabled"] = env_enabled

    env_model = os.getenv("AITRANS_RAG_VLM_MODEL", "").strip()
    env_base_url = os.getenv("AITRANS_RAG_VLM_BASE_URL", "").strip()
    if env_model:
        updates["model"] = env_model
    if env_base_url:
        updates["base_url"] = env_base_url

    resolved = config.model_copy(update=updates, deep=True)
    if not resolved.enabled or not resolved.inherit_ai_settings:
        return resolved

    ai_settings = settings.get("ai")
    if not isinstance(ai_settings, dict):
        return resolved
    provider = str(ai_settings.get("provider", "") or "").strip().lower().replace("-", "_")
    if provider != "openai_compatible":
        return resolved

    inherited: dict[str, Any] = {}
    if not resolved.model.strip():
        inherited_model = str(ai_settings.get("model", "") or "").strip()
        if inherited_model:
            inherited["model"] = inherited_model
    if not resolved.base_url.strip():
        inherited_base_url = str(ai_settings.get("base_url", "") or "").strip()
        if inherited_base_url:
            inherited["base_url"] = inherited_base_url
    return resolved.model_copy(update=inherited, deep=True)


def _resolve_visual_retrieval_config(
    config: RagVisualRetrievalConfig,
) -> RagVisualRetrievalConfig:
    """Resolve native visual retrieval overrides without loading the model."""

    updates: dict[str, Any] = {}
    env_enabled = _env_bool("AITRANS_RAG_VISUAL_RETRIEVAL_ENABLED")
    if env_enabled is not None:
        updates["enabled"] = env_enabled
    for env_name, field in (
        ("AITRANS_RAG_VISUAL_MODEL", "model"),
        ("AITRANS_RAG_VISUAL_MODEL_PATH", "model_path"),
        ("AITRANS_RAG_VISUAL_DEVICE", "device"),
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            updates[field] = value
    return config.model_copy(update=updates, deep=True)


def _build_runtime() -> RagRuntime:
    settings = SettingsManager().data
    raw_rag = settings.get("rag", {})
    config = RagConfig.model_validate(raw_rag if isinstance(raw_rag, dict) else {})

    visual_understanding = _resolve_visual_understanding_config(
        config.visual_understanding,
        settings,
    )
    visual_retrieval = _resolve_visual_retrieval_config(config.visual_retrieval)

    resolved_storage_path = _resolve_runtime_storage_path(config.vector_store.storage_path)
    vector_store_config = config.vector_store.model_copy(
        update={"storage_path": str(resolved_storage_path)}
    )
    visual_retrieval = visual_retrieval.model_copy(
        update={
            "storage_path": str(resolved_storage_path),
            "asset_storage_path": str(
                _resolve_runtime_storage_path(visual_retrieval.asset_storage_path)
            ),
        },
        deep=True,
    )
    config = config.model_copy(
        update={
            "visual_understanding": visual_understanding,
            "visual_retrieval": visual_retrieval,
            "vector_store": vector_store_config,
        },
        deep=True,
    )

    visual_description_provider = create_visual_description_provider(visual_understanding)
    visual_embedding_provider = create_visual_embedding_provider(visual_retrieval)

    model_manager = get_rag_model_manager()
    embedding = create_embedding_provider(config.embedding, model_manager=model_manager)

    shared_qdrant_client: QdrantClient | None = None
    visual_vector_store: QdrantVisualMultiVectorStore | None = None
    if visual_retrieval.enabled:
        # Qdrant Local permits one storage owner. Share one client across the
        # text and native-visual collections only when Stage 3 is enabled.
        shared_qdrant_client = QdrantClient(path=str(resolved_storage_path))
        vector_store = QdrantLocalVectorStore(
            vector_store_config,
            dimension=config.embedding.dimension,
            client=shared_qdrant_client,
        )
        visual_vector_store = create_adaptive_visual_vector_store(
            visual_retrieval,
            client=shared_qdrant_client,
        )
    else:
        # Preserve the pre-Stage-3 object lifecycle exactly when disabled.
        vector_store = QdrantLocalVectorStore(
            vector_store_config,
            dimension=config.embedding.dimension,
        )

    state_directory = resolved_storage_path.parent
    sparse = BM25SparseRetriever(state_directory / "bm25_index.json")
    manifest = IndexManifest(state_directory / "index_manifest.json")
    manifest.recover_interrupted_operations()

    base_retrieval = RetrievalService(
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        config=config.retrieval,
        reranker=Qwen3RerankerProvider(
            config.reranker,
            model_manager=model_manager,
        ),
    )
    retrieval: RetrievalService | VisualRetrievalService = base_retrieval
    if visual_retrieval.enabled and visual_embedding_provider and visual_vector_store:
        retrieval = AdaptiveVisualRetrievalService(
            base=base_retrieval,
            provider=visual_embedding_provider,
            store=visual_vector_store,
            config=visual_retrieval,
            default_final_top_k=config.retrieval.final_top_k,
        )

    structural_chunker = StructureAwareChunker(config.chunking)
    chunker = SemanticStructureAwareChunker(
        base_chunker=structural_chunker,
        semantic_config=config.semantic_chunking,
        embedding_provider=embedding,
    )
    base_index = IndexService(
        chunker=chunker,
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=manifest,
        parser=_build_document_parser(config),
        visual_description_provider=visual_description_provider,
        visual_understanding_config=visual_understanding,
    )
    index: IndexService | VisualAwareIndexService = base_index
    if visual_retrieval.enabled and visual_embedding_provider and visual_vector_store:
        coordinator = VisualIndexCoordinator(
            config=visual_retrieval,
            provider=visual_embedding_provider,
            store=visual_vector_store,
            manifest=manifest,
        )
        index = VisualAwareIndexService(base_index, coordinator, manifest)

    library = KnowledgeLibraryService(
        index_service=index,  # type: ignore[arg-type] - protocol-compatible sidecar wrapper
        manifest=manifest,
        config=config,
        embedding_provider=embedding,
        allowed_roots=_allowed_roots(),
        max_file_bytes=_max_file_bytes(),
    )
    return RagRuntime(
        config=config,
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=manifest,
        retrieval_service=retrieval,
        index_service=index,
        library_service=library,
        visual_description_provider=visual_description_provider,
        visual_embedding_provider=visual_embedding_provider,
        visual_vector_store=visual_vector_store,
        shared_qdrant_client=shared_qdrant_client,
    )


def get_rag_runtime() -> RagRuntime:
    global _runtime
    if _runtime is not None:
        return _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = _build_runtime()
        return _runtime


def get_retrieval_service() -> RetrievalService | VisualRetrievalService:
    return get_rag_runtime().retrieval_service


def get_knowledge_library_service() -> KnowledgeLibraryService:
    return get_rag_runtime().library_service


def close_rag_runtime() -> None:
    global _runtime
    with _runtime_lock:
        runtime = _runtime
        _runtime = None
    if runtime is None:
        return

    for provider in (
        runtime.visual_description_provider,
        runtime.visual_embedding_provider,
    ):
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    if runtime.shared_qdrant_client is not None:
        runtime.shared_qdrant_client.close()
    else:
        close = getattr(runtime.vector_store, "close", None)
        if callable(close):
            close()


__all__ = [
    "RagRuntime",
    "close_rag_runtime",
    "get_knowledge_library_service",
    "get_rag_runtime",
    "get_retrieval_service",
]
