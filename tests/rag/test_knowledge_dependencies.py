from __future__ import annotations

from functools import partial
from pathlib import Path

from backend.api import knowledge_dependencies
from backend.rag.config import RagAdvancedParsingConfig, RagConfig


def test_relative_rag_storage_is_anchored_to_application_data_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app_data = tmp_path / "app-data"
    working_directory = tmp_path / "arbitrary-working-directory"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    monkeypatch.setattr(knowledge_dependencies, "data_root", lambda: app_data)

    resolved = knowledge_dependencies._resolve_runtime_storage_path(
        "config/rag/qdrant"
    )

    assert resolved == (app_data / "config" / "rag" / "qdrant").resolve()
    assert working_directory not in resolved.parents


def test_absolute_rag_storage_path_is_preserved(tmp_path: Path) -> None:
    configured = tmp_path / "explicit" / "qdrant"

    assert knowledge_dependencies._resolve_runtime_storage_path(configured) == configured.resolve()


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
