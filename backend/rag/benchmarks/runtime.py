from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from backend.rag.chunking import StructureAwareChunker
from backend.rag.config import RagConfig
from backend.rag.embeddings import EmbeddingProvider, create_embedding_provider
from backend.rag.index_manifest import IndexManifest
from backend.rag.index_service import IndexService
from backend.rag.model_manager import ModelManager
from backend.rag.parsers import parse_document
from backend.rag.rerankers import Qwen3RerankerProvider
from backend.rag.rerankers.base import RerankerProvider
from backend.rag.retrieval_service import RetrievalService
from backend.rag.sparse import BM25SparseRetriever
from backend.rag.stores import QdrantLocalVectorStore


@dataclass(slots=True)
class BenchmarkRagRuntime:
    """RAG components backed by storage owned exclusively by one benchmark."""

    root: Path
    config: RagConfig
    embedding_provider: EmbeddingProvider
    vector_store: QdrantLocalVectorStore
    sparse_retriever: BM25SparseRetriever
    manifest: IndexManifest
    chunker: StructureAwareChunker
    retrieval_service: RetrievalService
    index_service: IndexService

    def close(self) -> None:
        close = getattr(self.vector_store, "close", None)
        if callable(close):
            close()
        close = getattr(self.embedding_provider, "close", None)
        if callable(close):
            close()


def _resolved_root(
    storage_root: str | Path | None,
    *,
    production_storage_paths: tuple[Path, ...],
) -> Path:
    if storage_root is None:
        from app.infrastructure.paths import data_root

        storage_root = data_root() / "benchmarks" / "qasper" / "runtime"
    root = Path(storage_root).expanduser().resolve()
    for production_storage in production_storage_paths:
        if root == production_storage or root in production_storage.parents:
            raise ValueError("benchmark storage must not contain production RAG storage")
        if production_storage in root.parents:
            raise ValueError("benchmark storage must not be inside production RAG storage")
    return root


def build_benchmark_rag_runtime(
    storage_root: str | Path | None = None,
    *,
    config: RagConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: RerankerProvider | None = None,
    model_manager: ModelManager | None = None,
) -> BenchmarkRagRuntime:
    """Build an isolated runtime while reusing AITrans' existing RAG services.

    The caller owns ``storage_root``. Qdrant, BM25, and the manifest are all
    placed below it, and a path-specific collection name prevents accidental
    collection reuse if a Qdrant directory is copied into another workspace.
    No user Knowledge runtime or settings singleton is loaded here.
    """

    source_config = config or RagConfig()
    isolated_config = source_config.model_copy(deep=True)
    from app.infrastructure.paths import data_root

    configured_production_storage = Path(
        source_config.vector_store.storage_path
    ).expanduser()
    if not configured_production_storage.is_absolute():
        configured_production_storage = data_root() / configured_production_storage
    production_storage_paths = (
        Path("config/rag/qdrant").resolve(),
        (data_root() / "config" / "rag" / "qdrant").resolve(),
        configured_production_storage.resolve(),
    )
    root = _resolved_root(
        storage_root,
        production_storage_paths=production_storage_paths,
    )
    root.mkdir(parents=True, exist_ok=True)
    vector_root = root / "qdrant"
    collection_suffix = sha256(str(root).encode("utf-8")).hexdigest()[:12]
    isolated_config.vector_store = isolated_config.vector_store.model_copy(
        update={
            "storage_path": str(vector_root),
            "collection_name": f"aitrans_benchmark_{collection_suffix}",
        }
    )
    # QASPER is a text benchmark. Keep optional production-only visual indexes
    # out of this runtime even if a caller passes a user-facing RAG config.
    isolated_config.visual_retrieval = isolated_config.visual_retrieval.model_copy(
        update={"enabled": False}, deep=True
    )
    isolated_config.visual_understanding = isolated_config.visual_understanding.model_copy(
        update={"enabled": False}, deep=True
    )

    if model_manager is None and (embedding_provider is None or reranker is None):
        model_manager = ModelManager()
    embedding = embedding_provider or create_embedding_provider(
        isolated_config.embedding,
        model_manager=model_manager,
    )
    vector_store = QdrantLocalVectorStore(
        isolated_config.vector_store,
        dimension=isolated_config.embedding.dimension,
    )
    sparse = BM25SparseRetriever(root / "bm25_index.json")
    manifest = IndexManifest(root / "index_manifest.json")
    manifest.recover_interrupted_operations()
    chunker = StructureAwareChunker(isolated_config.chunking)
    retrieval = RetrievalService(
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        config=isolated_config.retrieval,
        reranker=reranker
        or Qwen3RerankerProvider(
            isolated_config.reranker,
            model_manager=model_manager,
        ),
    )
    index = IndexService(
        chunker=chunker,
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=manifest,
        parser=parse_document,
    )
    return BenchmarkRagRuntime(
        root=root,
        config=isolated_config,
        embedding_provider=embedding,
        vector_store=vector_store,
        sparse_retriever=sparse,
        manifest=manifest,
        chunker=chunker,
        retrieval_service=retrieval,
        index_service=index,
    )


__all__ = ["BenchmarkRagRuntime", "build_benchmark_rag_runtime"]
