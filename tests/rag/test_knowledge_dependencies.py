from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from backend.api import knowledge_dependencies
from backend.rag.config import (
    RagAdvancedParsingConfig,
    RagConfig,
    RagEmbeddingConfig,
    RagVisualUnderstandingConfig,
)


def test_runtime_qdrant_environment_selects_server_without_changing_default(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tests.rag.graph.test_indexer import Embedding

    configs = []
    monkeypatch.setenv("AITRANS_QDRANT_URL", "http://127.0.0.1:6335/")
    monkeypatch.setattr(knowledge_dependencies, "SettingsManager", lambda: SimpleNamespace(data={
        "rag": {"embedding": {"dimension": 4}, "graph": {"enabled": False},
            "vector_store": {"storage_path": str(tmp_path / "original-local")}}}))
    monkeypatch.setattr(knowledge_dependencies, "get_rag_model_manager", lambda: None)
    monkeypatch.setattr(knowledge_dependencies, "create_embedding_provider", lambda *a, **kw: Embedding())
    monkeypatch.setattr(knowledge_dependencies, "Qwen3RerankerProvider", lambda *a, **kw: None)
    def store(config, **kwargs):
        configs.append(config)
        return SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(knowledge_dependencies, "QdrantLocalVectorStore", store)
    runtime = knowledge_dependencies._build_runtime()
    assert configs[0].url == "http://127.0.0.1:6335"
    assert configs[0].storage_path == str(tmp_path / "original-local")
    assert runtime.config.vector_store.url == configs[0].url


def test_native_visual_memory_overrides_are_validated(monkeypatch):
    from backend.rag.config import RagVisualRetrievalConfig

    original = RagVisualRetrievalConfig()
    monkeypatch.setenv("AITRANS_RAG_VISUAL_QUANTIZATION", "nf4")
    monkeypatch.setenv("AITRANS_RAG_VISUAL_MAX_IMAGE_TOKENS", "256")
    monkeypatch.setenv("AITRANS_RAG_VISUAL_CACHE_DIR", "D:/visual-cache")
    resolved = knowledge_dependencies._resolve_visual_retrieval_config(original)
    assert resolved.quantization == "nf4" and resolved.max_image_tokens == 256
    assert resolved.cache_dir == "D:/visual-cache"
    assert original.quantization == "none"
    monkeypatch.setenv("AITRANS_RAG_VISUAL_MAX_IMAGE_TOKENS", "-1")
    with pytest.raises(ValueError):
        knowledge_dependencies._resolve_visual_retrieval_config(original)


@pytest.mark.parametrize("base_url", ["", "https://api.deepseek.com/"])
def test_visual_config_inherits_chat_credentials_for_same_endpoint(base_url):
    configured = RagVisualUnderstandingConfig(enabled=True, base_url=base_url)
    resolved = knowledge_dependencies._resolve_visual_understanding_config(
        configured,
        {"ai": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        }},
    )

    assert resolved.credential_provider == "deepseek"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.base_url.rstrip("/") == "https://api.deepseek.com"
    assert configured.credential_provider == "openai_compatible"


def test_visual_config_does_not_forward_chat_credentials_to_another_endpoint():
    configured = RagVisualUnderstandingConfig(
        enabled=True, model="vision", base_url="https://vision.example/v1"
    )
    resolved = knowledge_dependencies._resolve_visual_understanding_config(
        configured,
        {"ai": {"provider": "deepseek", "base_url": "https://api.deepseek.com"}},
    )

    assert resolved == configured


def test_relative_rag_storage_is_anchored_to_application_data_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app_data = tmp_path / "app-data"
    working_directory = tmp_path / "arbitrary-working-directory"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(knowledge_dependencies, "data_root", lambda: app_data)

    resolved = knowledge_dependencies._resolve_runtime_storage_path("config/rag/qdrant")

    assert resolved == (app_data / "config" / "rag" / "qdrant").resolve()
    assert working_directory not in resolved.parents


def test_absolute_rag_storage_path_is_preserved(tmp_path: Path) -> None:
    configured = tmp_path / "explicit" / "qdrant"

    assert (
        knowledge_dependencies._resolve_runtime_storage_path(configured)
        == configured.resolve()
    )


@pytest.mark.parametrize(
    ("enabled", "disable_after_build"), [(False, False), (True, False), (True, True)]
)
def test_optional_graph_runtime_shares_index_and_query_lifecycle(
    tmp_path, monkeypatch, enabled, disable_after_build
):
    from types import SimpleNamespace

    from backend.rag.index_manifest import IndexStatus
    from tests.rag.graph.test_indexer import ControlledExtractor, Embedding

    settings = {
        "rag": {
            "embedding": {"dimension": 4},
            "vector_store": {"storage_path": str(tmp_path / "qdrant")},
            "graph": {"enabled": enabled},
        }
    }
    monkeypatch.setattr(
        knowledge_dependencies,
        "SettingsManager",
        lambda: SimpleNamespace(data=settings),
    )
    monkeypatch.setattr(knowledge_dependencies, "get_rag_model_manager", lambda: None)
    monkeypatch.setattr(
        knowledge_dependencies,
        "create_embedding_provider",
        lambda *a, **kw: Embedding(),
    )
    monkeypatch.setattr(
        knowledge_dependencies, "Qwen3RerankerProvider", lambda *a, **kw: None
    )
    source = ControlledExtractor()
    closed = []
    source.close = lambda: closed.append(True)
    calls = []

    def create_source():
        calls.append(True)
        return source

    monkeypatch.setattr(
        knowledge_dependencies, "_create_graph_extraction_service", create_source
    )
    runtime = knowledge_dependencies._build_runtime()
    monkeypatch.setattr(knowledge_dependencies, "_runtime", runtime)
    try:
        paper = tmp_path / "paper.txt"
        paper.write_text("Alpha uses Beta. Beta uses Gamma.")
        indexed = runtime.index_service.index_document(paper)
        assert indexed.status is IndexStatus.READY
        assert calls == ([True] if enabled else [])
        assert (tmp_path / "graph.sqlite3").exists() is enabled
        result = runtime.retrieval_service.retrieve(
            "Alpha",
            dense_enabled=False,
            graph_enabled=enabled,
            small_to_big_enabled=False,
        )
        assert result.metadata["graph_hits"] == (1 if enabled else 0)
        if enabled:
            assert any(path.edge_ids for path in result.candidates[0].graph_paths)
            previous = runtime.manifest.get(indexed.document_id).generation_id
            replaced = runtime.index_service.reindex_document(paper)
            assert replaced.status is IndexStatus.READY
            assert runtime.manifest.get(indexed.document_id).generation_id != previous
        if disable_after_build:
            knowledge_dependencies.close_rag_runtime()
            settings["rag"]["graph"]["enabled"] = False
            runtime = knowledge_dependencies._build_runtime()
            monkeypatch.setattr(knowledge_dependencies, "_runtime", runtime)
            assert runtime.graph_extraction_service is None
            assert (
                runtime.index_service.reindex_document(paper).status is IndexStatus.READY
            )
            assert calls == [True]
        assert runtime.index_service.delete_document(indexed.document_id)
        if enabled:
            import sqlite3

            with sqlite3.connect(tmp_path / "graph.sqlite3") as connection:
                for table in (
                    "entity",
                    "alias",
                    "relation",
                    "relation_span",
                    "chunk_entity",
                    "graph_generation",
                ):
                    assert (
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        == 0
                    )
        after = runtime.retrieval_service.retrieve(
            "Alpha", dense_enabled=False, graph_enabled=runtime.config.graph.enabled
        )
        assert after.candidates == []
        assert after.metadata["graph_hits"] == 0
    finally:
        knowledge_dependencies.close_rag_runtime()
    assert closed == ([True] if enabled else [])


def test_runtime_document_parser_binds_advanced_pdf_profile() -> None:
    config = RagConfig(
        advanced_parsing=RagAdvancedParsingConfig(
            enabled=True,
            layout_enabled=True,
            table_enabled=True,
            ocr_enabled=False,
            formula_enabled=True,
        )
    )

    parser = knowledge_dependencies._build_document_parser(config)

    assert isinstance(parser, partial)
    bound = parser.keywords["advanced_config"]
    assert bound == config.advanced_parsing
    assert bound is not config.advanced_parsing
    assert bound.enabled is True
    assert bound.table_enabled is True
    assert bound.formula_enabled is True


def test_embedding_runtime_overrides_batch_and_first_use_warmup(
    monkeypatch,
) -> None:
    configured = RagEmbeddingConfig(batch_size=8, warmup=True)
    monkeypatch.setenv("AITRANS_RAG_EMBEDDING_BATCH_SIZE", "4")
    monkeypatch.setenv("AITRANS_RAG_EMBEDDING_WARMUP", "off")

    resolved = knowledge_dependencies._resolve_embedding_runtime_config(configured)

    assert resolved.batch_size == 4
    assert resolved.warmup is False
    assert configured.batch_size == 8
    assert configured.warmup is True


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "AITRANS_RAG_EMBEDDING_BATCH_SIZE",
            "0",
            "must be a positive integer",
        ),
        ("AITRANS_RAG_EMBEDDING_BATCH_SIZE", "many", "must be a positive integer"),
        ("AITRANS_RAG_EMBEDDING_WARMUP", "sometimes", "must be a boolean value"),
    ],
)
def test_invalid_embedding_runtime_overrides_fail_fast(
    monkeypatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        knowledge_dependencies._resolve_embedding_runtime_config(RagEmbeddingConfig())
